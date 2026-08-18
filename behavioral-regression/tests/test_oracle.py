from __future__ import annotations

import pytest
from agent_core import OrderProbeResult, PairwiseItem, VerbosityProbeResult

from behavioral_regression.config import BRConfig
from behavioral_regression.judge import JVerdict
from behavioral_regression.oracle import build_judge_calibration_report, validate_judge


def _verdicts(labels):
    return [JVerdict(label=lbl, confidence=0.9) for lbl in labels]


def _passing_order() -> OrderProbeResult:
    return OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True)


def _passing_verbosity() -> VerbosityProbeResult:
    return VerbosityProbeResult(
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


def _canary(item_id: str, expected: str) -> PairwiseItem:
    return PairwiseItem(
        item_id=item_id,
        prompt="p",
        answer_a="a",
        answer_b="b",
        family_a="gpt",
        family_b="claude",
        expected=expected,
        canary_kind="known_equal" if expected == "tie" else "clearly_better",
    )


def test_length_mismatch_raises():
    with pytest.raises(ValueError, match="aligned"):
        validate_judge(_verdicts([True]), [True, False], BRConfig())


def test_perfect_agreement_gates():
    cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.6)
    labels = [True, False] * 20
    rep = validate_judge(_verdicts(labels), labels, cfg)
    assert rep.kappa == 1.0
    assert rep.may_gate is True


def test_disagreement_does_not_gate():
    cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.9)
    judge = [True, False] * 20
    human = [False, True] * 20  # systematic disagreement
    rep = validate_judge(_verdicts(judge), human, cfg)
    assert rep.may_gate is False


def test_below_power_is_directional_only():
    cfg = BRConfig(power_min_sample=100, min_judge_kappa=0.1)
    labels = [True, False, True, False]
    rep = validate_judge(_verdicts(labels), labels, cfg)
    assert rep.directional_only is True
    assert rep.may_gate is False


def test_indeterminates_excluded():
    cfg = BRConfig(power_min_sample=2, min_judge_kappa=0.5)
    judge = [None, True, False, None]
    human = [True, True, False, False]
    rep = validate_judge(_verdicts(judge), human, cfg)
    assert rep.n_codeterminate == 2  # only the two co-determinate pairs count


# --- build_judge_calibration_report --------------------------------------------


def test_build_report_length_mismatch_raises():
    with pytest.raises(ValueError, match="aligned"):
        build_judge_calibration_report(
            "j1",
            "art-1",
            _verdicts([True]),
            [True, False],
            BRConfig(),
            order_flip=_passing_order(),
            verbosity=_passing_verbosity(),
            self_preference=None,
            canaries=[],
            canary_verdicts=[],
        )


def test_build_report_composes_agreement_and_bias_probes():
    cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.6)
    labels = [True, False] * 20
    canaries = [_canary("c1", "tie")]

    report = build_judge_calibration_report(
        "j1",
        "art-1",
        _verdicts(labels),
        labels,
        cfg,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=canaries,
        canary_verdicts=["tie"],
    )

    assert report.judge_id == "j1"
    assert report.artifact_id == "art-1"
    assert report.n_total == len(labels)
    assert report.n_codeterminate == len(labels)  # every pair is co-determinate here
    assert report.kappa == 1.0
    assert report.percent_agreement == 1.0  # perfect agreement, matches kappa's po
    assert report.agreement_may_gate is True
    assert report.canary_pass_rate == 1.0
    assert report.may_gate is True  # agreement + both passing bias probes


def test_build_report_percent_agreement_scoped_to_codeterminate_pairs():
    cfg = BRConfig(power_min_sample=1, min_judge_kappa=0.0)
    judge = [None, True, False, True]  # first pair indeterminate
    human = [True, True, False, False]  # disagree on the last codeterminate pair

    report = build_judge_calibration_report(
        "j1",
        "art-1",
        _verdicts(judge),
        human,
        cfg,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=[_canary("c1", "tie")],
        canary_verdicts=["tie"],
    )

    assert report.n_codeterminate == 3  # the None pair is excluded
    assert report.percent_agreement == pytest.approx(2 / 3)  # 2 of 3 codeterminate pairs agree


def test_build_report_no_codeterminate_pairs_does_not_crash():
    cfg = BRConfig(power_min_sample=1, min_judge_kappa=0.5)
    judge = [None, None]
    human = [True, False]

    report = build_judge_calibration_report(
        "j1",
        "art-1",
        _verdicts(judge),
        human,
        cfg,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=[_canary("c1", "tie")],
        canary_verdicts=["tie"],
    )

    assert report.n_codeterminate == 0
    assert report.percent_agreement == 0.0
    assert report.directional_only is True
    assert report.may_gate is False  # underpowered -> advisory only, never crashes
