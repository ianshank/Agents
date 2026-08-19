#!/usr/bin/env python3
"""Validation script for F-057 - Judge bias calibration.

Checks:
    1.  ``ProbeConfig`` validates its fields; ``order_flip_rate``,
        ``verbosity_preference_delta`` and ``self_preference_breakdown`` produce
        correct counts/rates on hand-crafted examples, reusing ``wilson_interval``,
        and each fails (with a ``degenerate`` reason) once its informative-pair
        count is below ``cfg.min_pairs``, even when the measured rate already
        clears its own tolerance.
    2.  ``PairwiseItem`` cross-validates canary kind against ``expected``;
        ``PairwiseSet`` rejects duplicate IDs.
    3.  ``JudgeCalibrationReport.may_gate`` is false when any bias check fails
        even with acceptable agreement, and ``failing_checks`` names every
        currently-failing check, not just the first.
    4.  ``build_judge_calibration_report`` (agent_core) computes the canary pass
        rate correctly and rejects an empty canary list.
    5.  The engine orders programmatic scorers ahead of judges and skips a judge
        (recording no ``ScoreResult`` at all) once a programmatic scorer has
        already failed the item -- a judge's verdict cannot convert a fail into a
        pass. A duck-typed scorer that never defines ``uses_judge()`` does not
        crash the engine.
    6.  ``JudgeCalibrationGateConfig.calibration_artifact_id`` is required and
        non-empty.
    7.  ``require_calibration_for_judge_gating`` rejects a gate rule that targets
        a judge-backed scorer with no named calibration artifact, and allows it
        once one is named; a gate rule that does not target the judge needs none.
    8.  ``require_report_to_gate`` rejects an artifact-ID mismatch and a report
        that does not authorise gating (naming the failing check), and allows a
        matching, authorising report through.
    9.  ``behavioral_regression.build_judge_calibration_report`` composes
        ``validate_judge``'s agreement measurement with pre-computed bias probes
        into a full report without re-deriving either.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("agent-core", "flow-protocol", "flow-corpus", "behavioral-regression"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

from agent_core import PairwiseItem
from agent_core.judge_calibration import VerbosityProbeResult

# Shared fixtures: every check below that needs a passing verbosity probe or a
# canary item wants the same shape, varying at most a couple of fields.
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


def _canary(item_id: str, expected: str, canary_kind: str) -> PairwiseItem:
    return PairwiseItem(
        item_id=item_id,
        prompt="p",
        answer_a="a",
        answer_b="b",
        family_a="gpt",
        family_b="claude",
        expected=expected,
        canary_kind=canary_kind,
    )


def _check_probe_math(errors: list[str]) -> None:
    from agent_core import ProbeConfig, order_flip_rate, self_preference_breakdown, verbosity_preference_delta
    from agent_core.judge_calibration import OrderProbeResult, PairOutcome, VerbosityProbeResult

    cfg = ProbeConfig()
    _check(cfg.wilson_z > 0, "ProbeConfig.wilson_z is positive by default", errors)
    try:
        ProbeConfig(min_pairs=0)
        _check(False, "ProbeConfig rejects min_pairs < 1", errors)
    except Exception:
        _check(True, "ProbeConfig rejects min_pairs < 1", errors)

    # verdicts_ba is translated back to original terms via _SWAP before comparing:
    # idx 0-1 agree once translated (no flip); idx 2-3 disagree (flip) -> 2 of 4.
    ab = ["a", "b", "a", "b"]
    ba = ["b", "a", "a", "b"]
    order = order_flip_rate(ab, ba, cfg)
    _check(isinstance(order, OrderProbeResult) and order.n == 4, "order_flip_rate: n reflects pair count", errors)
    _check(order.flips == 2, "order_flip_rate: counts a flipped winner across the swap", errors)

    verdicts = ["concise"] * 3 + ["expanded"] * 7
    verbosity = verbosity_preference_delta(verdicts, cfg)
    _check(
        isinstance(verbosity, VerbosityProbeResult) and abs(verbosity.expanded_win_rate - 0.7) < 1e-9,
        "verbosity_preference_delta: expanded_win_rate reflects the 'expanded' share",
        errors,
    )

    outcomes = [
        PairOutcome(family_a="gpt", family_b="claude", winner="a"),  # gpt (a) wins
        PairOutcome(family_a="gpt", family_b="claude", winner="a"),  # gpt (a) wins
        PairOutcome(family_a="claude", family_b="gpt", winner="b"),  # gpt (b) wins
        PairOutcome(family_a="claude", family_b="human", winner="a"),  # neither side is gpt -> uninformative
    ]
    self_pref = self_preference_breakdown("gpt", outcomes, cfg)
    _check(
        self_pref.same_family_n == 3,
        "self_preference_breakdown: a pair where neither candidate is the judge's family is not informative",
        errors,
    )
    _check(
        self_pref.same_family_win_rate == 1.0,
        "self_preference_breakdown: gpt wins all 3 informative pairs -> same_family_win_rate 1.0",
        errors,
    )

    # min_pairs enforcement (Copilot review finding, PR #160): a probe that clears its
    # tolerance on too few pairs must still fail once min_pairs exceeds the sample size.
    strict_cfg = ProbeConfig(min_pairs=30)
    tiny_order = order_flip_rate(["a", "b"], ["b", "a"], strict_cfg)  # n=2, 0 flips
    _check(
        tiny_order.passes is False and "insufficient pairs" in (tiny_order.degenerate or ""),
        "order_flip_rate: min_pairs floor fails an undersized probe even when it clears tolerance",
        errors,
    )
    tiny_verbosity = verbosity_preference_delta(["concise", "expanded"], strict_cfg)  # n=2
    _check(
        tiny_verbosity.passes is False and tiny_verbosity.degenerate is not None,
        "verbosity_preference_delta: min_pairs floor fails an undersized probe",
        errors,
    )
    tiny_self_pref = self_preference_breakdown(
        "gpt",
        [PairOutcome("gpt", "claude", "a"), PairOutcome("claude", "gpt", "a")],
        strict_cfg,
    )
    _check(
        tiny_self_pref.passes is False and tiny_self_pref.degenerate is not None,
        "self_preference_breakdown: min_pairs floor fails an undersized probe",
        errors,
    )
    # order.passes is already False under the default cfg (a real tolerance failure,
    # unrelated to min_pairs -- flip_rate=0.5 exceeds order_flip_tolerance=0.15), so this
    # only asserts the floor specifically, not the unrelated tolerance outcome.
    _check(
        order.degenerate is None,
        "order_flip_rate: default ProbeConfig (min_pairs=1) never trips the floor",
        errors,
    )


def _check_corpus_and_report(errors: list[str]) -> None:
    from agent_core import PairwiseSet
    from agent_core import build_judge_calibration_report as agent_core_build_report
    from agent_core.judge_calibration import OrderProbeResult
    from agent_core.judge_calibration_report import JudgeCalibrationReport

    try:
        _canary("x", expected="a", canary_kind="known_equal")  # inconsistent: known_equal implies 'tie'
        _check(False, "PairwiseItem rejects a known_equal canary with expected != 'tie'", errors)
    except Exception:
        _check(True, "PairwiseItem rejects a known_equal canary with expected != 'tie'", errors)

    item1 = PairwiseItem(item_id="p1", prompt="p", answer_a="a", answer_b="b", family_a="gpt", family_b="claude")
    try:
        PairwiseSet([item1, item1])
        _check(False, "PairwiseSet rejects duplicate item_ids", errors)
    except Exception:
        _check(True, "PairwiseSet rejects duplicate item_ids", errors)

    passing_order = OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True)
    failing_order = OrderProbeResult(n=10, flips=8, flip_rate=0.8, ci_low=0.5, ci_high=0.9, passes=False)

    def _mkreport(order_flip: OrderProbeResult, agreement_may_gate: bool) -> JudgeCalibrationReport:
        return JudgeCalibrationReport(
            schema_version="1.0.0",
            judge_id="j",
            artifact_id="a",
            n_total=100,
            n_codeterminate=90,
            percent_agreement=0.9,
            kappa=0.85,
            directional_only=False,
            agreement_may_gate=agreement_may_gate,
            order_flip=order_flip,
            verbosity=_PASSING_VERBOSITY,
            self_preference=None,
            canary_pass_rate=1.0,
        )

    _check(
        _mkreport(failing_order, True).may_gate is False,
        "may_gate is False when a bias check fails despite acceptable agreement",
        errors,
    )
    _check(
        _mkreport(failing_order, True).failing_checks == ("order_flip",),
        "failing_checks names the specific failing bias check",
        errors,
    )
    _check(
        set(_mkreport(failing_order, False).failing_checks) == {"agreement_or_power", "order_flip"},
        "failing_checks names every failing check, not just the first",
        errors,
    )

    canaries = [
        _canary("c1", expected="tie", canary_kind="known_equal"),
        _canary("c2", expected="a", canary_kind="clearly_better"),
    ]
    built = agent_core_build_report(
        "j1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=passing_order,
        verbosity=_PASSING_VERBOSITY,
        self_preference=None,
        canaries=canaries,
        canary_verdicts=["tie", "b"],
    )
    _check(built.canary_pass_rate == 0.5, "build_judge_calibration_report: canary pass rate (1 of 2 correct)", errors)
    try:
        agent_core_build_report(
            "j1",
            "art-1",
            n_total=1,
            n_codeterminate=1,
            percent_agreement=1.0,
            kappa=1.0,
            directional_only=False,
            agreement_may_gate=True,
            order_flip=passing_order,
            verbosity=_PASSING_VERBOSITY,
            self_preference=None,
            canaries=[],
            canary_verdicts=[],
        )
        _check(False, "build_judge_calibration_report rejects an empty canary list", errors)
    except ValueError:
        _check(True, "build_judge_calibration_report rejects an empty canary list", errors)


def _check_engine_ordering(errors: list[str]) -> None:
    from eval_harness.config.models import EvalConfig
    from eval_harness.core.types import EvalItem, ScoreResult
    from eval_harness.engine import EvalEngine
    from eval_harness.plugins import SCORERS, TARGETS, bootstrap
    from eval_harness.version import SCHEMA_VERSION

    bootstrap()

    class _Dataset:
        def load(self):
            return [EvalItem(id="i1", inputs={}, expected=None)]

    class _FailingProgrammatic:
        name = "prog"

        def score(self, item, output, ctx):
            return ScoreResult(name=self.name, value=0.0, passed=False)

    class _DuckScorer:
        name = "duck"

        def score(self, item, output, ctx):
            return ScoreResult(name=self.name, value=1.0, passed=True)

    config = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
        }
    )
    judge_scorer = SCORERS.create("llm_judge", {"name": "quality"})
    target = TARGETS.create("echo", {})
    # _FailingProgrammatic/_DuckScorer deliberately omit uses_judge() -- proving the
    # *runtime* fallback for a duck-typed scorer that predates that method, which the
    # static Protocol check below doesn't model.
    engine = EvalEngine(
        config,
        dataset=_Dataset(),
        target=target,
        scorers=[judge_scorer, _FailingProgrammatic()],  # type: ignore[list-item]
        sinks=[],
    )
    _check(
        engine.scorers[0].name == "prog",
        "EvalEngine orders the programmatic scorer ahead of the judge-backed one",
        errors,
    )
    scored_names = {s.name for s in engine.run().items[0].scores}
    _check(
        "quality" not in scored_names,
        "a judge is skipped (no ScoreResult recorded) once a programmatic scorer has failed the item",
        errors,
    )

    try:
        EvalEngine(
            config,
            dataset=_Dataset(),
            target=target,
            scorers=[_DuckScorer()],  # type: ignore[list-item]
            sinks=[],
        ).run()
        _check(True, "a duck-typed scorer without uses_judge() does not crash the engine", errors)
    except AttributeError:
        _check(False, "a duck-typed scorer without uses_judge() does not crash the engine", errors)


def _check_gating_config(errors: list[str]) -> None:
    import pydantic

    from eval_harness.agent_core_adapter import require_report_to_gate
    from eval_harness.config.models import EvalConfig, JudgeCalibrationGateConfig
    from eval_harness.gating import require_calibration_for_judge_gating
    from eval_harness.plugins import SCORERS, bootstrap
    from eval_harness.version import SCHEMA_VERSION

    bootstrap()

    try:
        JudgeCalibrationGateConfig(calibration_artifact_id="")
        _check(False, "JudgeCalibrationGateConfig rejects an empty artifact_id", errors)
    except pydantic.ValidationError:
        _check(True, "JudgeCalibrationGateConfig rejects an empty artifact_id", errors)
    _check(
        JudgeCalibrationGateConfig(calibration_artifact_id="run-1").calibration_artifact_id == "run-1",
        "JudgeCalibrationGateConfig accepts a named artifact_id",
        errors,
    )

    gated_config = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "judge": {"type": "mock", "params": {}},
            "gate": {"rules": [{"score": "quality", "metric": "mean", "min": 0.5}]},
        }
    )
    try:
        require_calibration_for_judge_gating(gated_config, [SCORERS.create("llm_judge", {"name": "quality"})])
        _check(False, "require_calibration_for_judge_gating rejects a gated judge with no named artifact", errors)
    except ValueError:
        _check(True, "require_calibration_for_judge_gating rejects a gated judge with no named artifact", errors)

    named_config = EvalConfig.model_validate(
        {**gated_config.model_dump(mode="json"), "judge_calibration": {"calibration_artifact_id": "run-1"}}
    )
    require_calibration_for_judge_gating(named_config, [SCORERS.create("llm_judge", {"name": "quality"})])
    _check(True, "require_calibration_for_judge_gating allows a gated judge once an artifact is named", errors)

    untargeted_config = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "judge": {"type": "mock", "params": {}},
            "gate": {"rules": [{"score": "acc", "metric": "mean", "min": 0.5}]},
        }
    )
    require_calibration_for_judge_gating(
        untargeted_config,
        [SCORERS.create("exact_match", {"name": "acc"}), SCORERS.create("llm_judge", {"name": "quality"})],
    )
    _check(True, "require_calibration_for_judge_gating needs nothing when the gate doesn't target the judge", errors)

    from agent_core import ProbeConfig, order_flip_rate
    from agent_core.judge_calibration import OrderProbeResult
    from agent_core.judge_calibration_report import JudgeCalibrationReport

    def _mkreport(order_flip: OrderProbeResult) -> JudgeCalibrationReport:
        return JudgeCalibrationReport(
            schema_version="1.0.0",
            judge_id="j",
            artifact_id="a",
            n_total=100,
            n_codeterminate=90,
            percent_agreement=0.9,
            kappa=0.85,
            directional_only=False,
            agreement_may_gate=True,
            order_flip=order_flip,
            verbosity=_PASSING_VERBOSITY,
            self_preference=None,
            canary_pass_rate=1.0,
        )

    ok_report = _mkreport(OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True))
    try:
        require_report_to_gate(ok_report, "wrong-id")
        _check(False, "require_report_to_gate rejects an artifact_id mismatch", errors)
    except ValueError:
        _check(True, "require_report_to_gate rejects an artifact_id mismatch", errors)

    biased_report = _mkreport(OrderProbeResult(n=10, flips=8, flip_rate=0.8, ci_low=0.5, ci_high=0.9, passes=False))
    try:
        require_report_to_gate(biased_report, "a")
        _check(False, "require_report_to_gate rejects a report that does not authorise gating", errors)
    except ValueError as exc:
        _check("order_flip" in str(exc), "require_report_to_gate names the failing check in the error", errors)

    # min_pairs review follow-up (4-lens review of PR #160): the degenerate reason must
    # reach the raised message itself, not just a bare check name -- Product and Architect
    # independently found this gap by reading require_report_to_gate directly.
    undersized_probe = order_flip_rate(["a"], ["b"], ProbeConfig(min_pairs=30))
    undersized_report = _mkreport(undersized_probe)
    try:
        require_report_to_gate(undersized_report, "a")
        _check(False, "require_report_to_gate rejects an undersized-probe report", errors)
    except ValueError as exc:
        _check(
            undersized_probe.degenerate in str(exc),
            "require_report_to_gate's error names an undersized probe's degenerate reason, "
            "not just the bare check name",
            errors,
        )

    require_report_to_gate(ok_report, "a")
    _check(True, "require_report_to_gate allows a matching, authorising report", errors)


def _check_behavioral_regression(errors: list[str]) -> None:
    from agent_core import percent_agreement
    from agent_core.judge_calibration import OrderProbeResult
    from behavioral_regression import BRConfig
    from behavioral_regression import build_judge_calibration_report as br_build_report
    from behavioral_regression.judge import JVerdict

    br_cfg = BRConfig(power_min_sample=5, min_judge_kappa=0.6)
    labels = [True, False] * 20
    br_verdicts = [JVerdict(label=lbl, confidence=0.9) for lbl in labels]
    br_report = br_build_report(
        "j1",
        "art-1",
        br_verdicts,
        labels,
        br_cfg,
        order_flip=OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True),
        verbosity=_PASSING_VERBOSITY,
        self_preference=None,
        canaries=[_canary("c1", expected="tie", canary_kind="known_equal")],
        canary_verdicts=["tie"],
    )
    _check(
        br_report.kappa == 1.0 and br_report.percent_agreement == 1.0,
        "behavioral_regression.build_judge_calibration_report composes kappa and percent_agreement from one measurement",
        errors,
    )
    _check(
        percent_agreement([1, 0], [1, 0]) == 1.0,
        "agent_core.percent_agreement is exposed standalone and importable from agent_core",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_probe_math(errors)
    _check_corpus_and_report(errors)
    _check_engine_ordering(errors)
    _check_gating_config(errors)
    _check_behavioral_regression(errors)
    return report(logger, "F-057", errors)


if __name__ == "__main__":
    sys.exit(main())
