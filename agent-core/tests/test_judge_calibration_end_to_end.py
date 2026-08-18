"""End-to-end judge calibration: a synthetic biased judge's own verdicts flow
through the real probe -> report pipeline, not hand-typed verdict strings.

Mirrors add-repeat-reliability-metrics' own M8 pipeline precedent (F-056): unit
tests exercise each function in isolation elsewhere (test_judge_calibration.py,
test_judge_calibration_report.py); this file proves the full chain end to end,
per extend-judge-calibration/tasks.md Group 6 -- "swapping answer order exposes
a biased judge; an uncalibrated judge cannot gate."
"""

from __future__ import annotations

from agent_core import ProbeConfig
from agent_core.judge_calibration import OrderProbeResult, VerbosityProbeResult, order_flip_rate
from agent_core.judge_calibration_report import build_judge_calibration_report
from agent_core.pairwise import PairwiseItem, PairwiseSet

CFG = ProbeConfig()

_PASSING_VERBOSITY = VerbosityProbeResult(
    n=10,
    ties=0,
    concise_wins=5,
    expanded_wins=5,
    expanded_win_rate=0.5,
    preference_delta=0.0,
    ci_low=0.2,
    ci_high=0.8,
    passes=True,
)


def _position_biased_judge(shown_first: str, shown_second: str) -> str:
    """A synthetic judge that always prefers whichever candidate it sees first,
    regardless of content -- the exact bias spec.md's order-flip scenario names."""
    return "a"


def _corpus(n: int) -> PairwiseSet:
    return PairwiseSet(
        tuple(
            PairwiseItem(
                item_id=f"p{i}",
                prompt=f"prompt {i}",
                answer_a=f"answer-A-{i}",
                answer_b=f"answer-B-{i}",
                family_a="gpt",
                family_b="claude",
            )
            for i in range(n)
        )
    )


def _canary() -> PairwiseItem:
    return PairwiseItem(
        item_id="canary-1",
        prompt="p",
        answer_a="same answer",
        answer_b="same answer",
        family_a="gpt",
        family_b="claude",
        expected="tie",
        canary_kind="known_equal",
    )


def test_a_position_biased_judges_own_verdicts_flip_on_every_pair() -> None:
    """The judge is graded in both orders; its own verdicts -- not hand-typed
    strings -- are what order_flip_rate consumes (spec.md's own scenario)."""
    corpus = _corpus(10)

    verdicts_ab = [_position_biased_judge(item.answer_a, item.answer_b) for item in corpus.items]
    # Swapped presentation: answer_b is shown first. The biased judge still picks
    # "whichever is first" -- its own returned "a" now means answer_b won.
    verdicts_ba = [_position_biased_judge(item.answer_b, item.answer_a) for item in corpus.items]

    result = order_flip_rate(verdicts_ab, verdicts_ba, CFG)

    assert isinstance(result, OrderProbeResult)
    assert result.n == 10
    assert result.flips == 10  # every pair's winner changes once the swap is translated back
    assert result.flip_rate == 1.0
    assert result.passes is False


def test_a_biased_judges_report_does_not_authorise_gating() -> None:
    """The order-flip result measured above -- not a hand-built passing one --
    is what determines may_gate. Acceptable agreement is not enough on its own."""
    corpus = _corpus(10)
    verdicts_ab = [_position_biased_judge(item.answer_a, item.answer_b) for item in corpus.items]
    verdicts_ba = [_position_biased_judge(item.answer_b, item.answer_a) for item in corpus.items]
    measured_order_flip = order_flip_rate(verdicts_ab, verdicts_ba, CFG)
    assert measured_order_flip.passes is False  # sanity: this is the biased result

    canary = _canary()
    report = build_judge_calibration_report(
        "position-biased-judge",
        "art-e2e-1",
        n_total=100,
        n_codeterminate=90,
        percent_agreement=0.95,  # deliberately high -- agreement alone must not save it
        kappa=0.9,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=measured_order_flip,
        verbosity=_PASSING_VERBOSITY,
        self_preference=None,
        canaries=[canary],
        canary_verdicts=["tie"],
    )

    assert report.may_gate is False
    assert "order_flip" in report.failing_checks


def test_an_underpowered_judge_also_cannot_gate() -> None:
    """spec.md's second 'uncalibrated' scenario: below the power floor, the
    result is directional only, independent of whether any bias probe passes."""
    passing_order = OrderProbeResult(
        n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True
    )
    canary = _canary()

    report = build_judge_calibration_report(
        "underpowered-judge",
        "art-e2e-2",
        n_total=3,
        n_codeterminate=3,  # below a real power floor -- the caller (behavioral_regression
        # in production) is the one that sets agreement_may_gate=False in this situation
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=True,
        agreement_may_gate=False,
        order_flip=passing_order,
        verbosity=_PASSING_VERBOSITY,
        self_preference=None,
        canaries=[canary],
        canary_verdicts=["tie"],
    )

    assert report.directional_only is True
    assert report.may_gate is False
    assert "agreement_or_power" in report.failing_checks
