#!/usr/bin/env python3
"""Validation script for F-062 - Gate-decision provenance and advisory gate rules.

Checks:
    1.  Provenance: ``EvalEngine.run`` attaches the gate's verdict to the
        ``RunResult`` *before* the sink loop, so every exported artifact carries
        it. Previously the gate ran in ``cli.py`` after ``run()`` returned and
        the verdict existed only as process output. A run with no gate
        configured carries no decision and serializes byte-identically to the
        pre-change payload.
    2.  Advisory rules: ``GateRule.report_only`` defaults False; an advisory
        rule still requires a bound (the flag does not relax
        ``_require_at_least_one_bound``); an unmet advisory rule lands in the
        advisory channel and does not fail the gate; it never softens a
        blocking failure in the same run.
    3.  Single evaluation path: the same run evaluated as advisory and as
        blocking produces the identical verdict, differing only in which
        channel it is filed to. Two evaluation paths would let advisory and
        blocking drift during exactly the soak meant to establish trust in a
        threshold.
    4.  Calibration guard: ``require_calibration_for_judge_gating`` counts only
        non-advisory rules as gating, so a judge-backed scorer may be
        *measured* without a calibration artifact -- otherwise the labelled
        corpus that produces the artifact would be unreachable. The
        fail-closed refusal is unchanged for any rule that can block, and
        promoting an advisory rule re-arms it.
    5.  Governance: the CLI reads the recorded decision rather than
        re-evaluating (one evaluation, so the artifact and the exit code cannot
        disagree); ``architecture.yaml`` declares the ``engine -> gating`` edge
        the change introduces -- skipped gracefully when ``grimp`` is absent,
        mirroring F_060's handling, since the dedicated CI job covers it.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

SCORE = "acc"
#: A bound no score in [0, 1] can satisfy, so a rule using it is unmet whatever
#: the target produced. Keeps these checks independent of any target's output.
UNSATISFIABLE = 1.1


def _run_result(mean: float = 0.4):
    from eval_harness.core.types import RunResult, ScoreAggregate

    now = datetime.now(UTC)
    return RunResult(
        run_id="r",
        config_name="c",
        items=[],
        aggregate={SCORE: ScoreAggregate(count=3, mean=mean, pass_rate=mean)},
        started_at=now,
        finished_at=now,
    )


def _eval_config(rules: list[dict]):
    from eval_harness.config.models import EvalConfig
    from eval_harness.version import SCHEMA_VERSION

    return EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {
                "type": "inline",
                "params": {"items": [{"id": "i1", "inputs": {"q": "x"}, "expected": "x"}]},
            },
            "target": {"type": "echo"},
            "scorers": [{"type": "exact_match", "params": {"name": SCORE}}],
            "gate": {"rules": rules},
        }
    )


def _check_provenance(errors: list[str]) -> None:
    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.engine import EvalEngine

    seen: list[object] = []

    class _RecordingSink:
        def emit(self, run) -> None:
            seen.append(run.gate)

    engine = EvalEngine.from_config(_eval_config([{"score": SCORE, "min": 0.0}]))
    engine.sinks = [_RecordingSink()]
    run = engine.run()

    _check(
        len(seen) == 1 and seen[0] is not None and seen[0] is run.gate,
        "the gate decision reaches the sinks (attached before the emit loop)",
        errors,
    )

    # A failure that belongs to no rule must still be explained in the artifact:
    # _item_error_failures has no GateRuleRecord behind it, and rendering only
    # rule rows produced a report captioned FAIL whose every row read "met".
    from eval_harness.core._execution_strategies import ITEM_ERROR_SCORE_NAME
    from eval_harness.core.types import EvalItem, ItemResult, ScoreResult, TargetOutput
    from eval_harness.gating import evaluate_gate
    from eval_harness.sinks import HtmlFileSink

    reduced = _run_result(0.9)
    reduced.items = [
        ItemResult(
            item=EvalItem(id="i1", inputs={}),
            output=TargetOutput(output=None, error="boom"),
            scores=[ScoreResult(ITEM_ERROR_SCORE_NAME, value=0.0, passed=False)],
        )
    ]
    reduced.gate = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.1)]), reduced).to_decision()
    rendered = HtmlFileSink(path=os.path.join(PROJECT_ROOT, "build", "f062-gate.html")).render(reduced)
    _check(
        not reduced.gate.passed
        and all(r.met for r in reduced.gate.rules)
        and "Gate-level findings" in rendered
        and "failed before scoring" in rendered,
        "a gate failure belonging to no rule is still explained in the html report",
        errors,
    )

    payload = _run_result().to_dict()
    _check("gate" not in payload, "an ungated run omits the gate key entirely", errors)
    _check(
        set(payload) == {"run_id", "config_name", "started_at", "finished_at", "aggregate", "items"},
        "an ungated run's payload keys are unchanged from the pre-change shape",
        errors,
    )

    from eval_harness.gating import default_gate_evaluator

    _check(
        default_gate_evaluator(None, _run_result()) is None,
        "no gate configured yields no decision, rather than a vacuous pass",
        errors,
    )

    ruleless = default_gate_evaluator(GateConfig(rules=[]), _run_result())
    _check(
        ruleless is not None and ruleless.passed is True,
        "a configured but ruleless gate keeps its historical passing verdict",
        errors,
    )


def _check_advisory_rules(errors: list[str]) -> None:
    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.gating import evaluate_gate

    _check(GateRule(score=SCORE, min=0.5).report_only is False, "report_only defaults to False", errors)

    try:
        GateRule(score=SCORE, report_only=True)
        _check(False, "an advisory rule with no bound is rejected", errors)
    except ValueError:
        _check(True, "an advisory rule with no bound is rejected", errors)

    advisory_only = evaluate_gate(
        GateConfig(rules=[GateRule(score=SCORE, min=UNSATISFIABLE, report_only=True)]), _run_result()
    )
    _check(
        advisory_only.passed is True and len(advisory_only.advisory) == 1 and not advisory_only.failures,
        "an unmet advisory rule is filed to the advisory channel and does not fail the gate",
        errors,
    )

    mixed = evaluate_gate(
        GateConfig(
            rules=[
                GateRule(score=SCORE, min=UNSATISFIABLE, report_only=True),
                GateRule(score=SCORE, min=UNSATISFIABLE),
            ]
        ),
        _run_result(),
    )
    _check(
        mixed.passed is False and len(mixed.failures) == 1 and len(mixed.advisory) == 1,
        "an advisory rule never softens a blocking failure in the same run",
        errors,
    )


def _check_single_evaluation_path(errors: list[str]) -> None:
    from eval_harness.config.models import GateConfig, GateRule
    from eval_harness.gating import evaluate_gate

    agreed = True
    for mean in (0.0, 0.4, 0.9, 1.0):
        run = _run_result(mean)
        (blocking,) = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.5)]), run).rules
        (advisory,) = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.5, report_only=True)]), run).rules
        agreed &= (
            blocking.met == advisory.met
            and blocking.observed == advisory.observed
            and blocking.detail == advisory.detail
            and blocking.advisory is False
            and advisory.advisory is True
        )
    _check(agreed, "advisory and blocking rules reach the identical verdict on the identical run", errors)


def _check_calibration_guard(errors: list[str]) -> None:
    from eval_harness.core.interfaces import Scorer
    from eval_harness.core.types import EvalItem, RunContext, ScoreResult, TargetOutput
    from eval_harness.gating import require_calibration_for_judge_gating

    class _JudgeBacked(Scorer):
        """A scorer whose verdict depends on a judge.

        Implements the real ``Scorer`` protocol rather than duck-typing a
        partial stand-in: the guard resolves ``.name``/``.uses_judge()`` off
        the *constructed* scorer, so a stub that is not actually a scorer would
        be testing a different call than the one production makes.
        """

        default_name = "judged"

        def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
            return ScoreResult(self.name, value=1.0, passed=True)

        def uses_judge(self) -> bool:
            return True

    scorers: list[Scorer] = [_JudgeBacked()]

    try:
        require_calibration_for_judge_gating(
            _eval_config([{"score": "judged", "min": 0.5, "report_only": True}]), scorers
        )
        _check(True, "an advisory judge-backed rule needs no calibration artifact", errors)
    except ValueError:
        _check(False, "an advisory judge-backed rule needs no calibration artifact", errors)

    try:
        require_calibration_for_judge_gating(_eval_config([{"score": "judged", "min": 0.5}]), scorers)
        _check(False, "a blocking judge-backed rule is still refused without an artifact", errors)
    except ValueError:
        _check(True, "a blocking judge-backed rule is still refused without an artifact", errors)

    try:
        require_calibration_for_judge_gating(
            _eval_config(
                [
                    {"score": "judged", "min": 0.5, "report_only": True},
                    {"score": "judged", "min": 0.6},
                ]
            ),
            scorers,
        )
        _check(False, "other advisory rules do not soften the refusal", errors)
    except ValueError:
        _check(True, "other advisory rules do not soften the refusal", errors)


def _check_governance(errors: list[str]) -> None:
    import eval_harness.cli as cli

    _check(
        not hasattr(cli, "evaluate_gate"),
        "the CLI reads the recorded decision instead of re-evaluating the gate",
        errors,
    )

    import yaml

    with open(os.path.join(PROJECT_ROOT, "architecture.yaml"), encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh)
    _check(
        "gating" in manifest["dependencies"]["engine"],
        "architecture.yaml declares the engine -> gating edge",
        errors,
    )

    # The declared edge must also be a real one. A manifest entry nothing uses is
    # the "declared but unused" warning the drift guard already reports; asserting
    # the import here keeps the declaration honest without needing grimp. The full
    # graph check stays with the dedicated "architecture drift + freshness" CI job.
    import eval_harness.engine as engine_module
    from eval_harness.gating import default_gate_evaluator

    _check(
        engine_module.default_gate_evaluator is default_gate_evaluator,
        "the engine reaches its gate verdict through gating.default_gate_evaluator",
        errors,
    )
    _check(
        engine_module.EvalEngine.__init__.__kwdefaults__ is not None
        and engine_module.EvalEngine.__init__.__kwdefaults__.get("gate_evaluator") is default_gate_evaluator,
        "the gate evaluator is an injectable seam defaulting to the harness policy",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_provenance(errors)
    _check_advisory_rules(errors)
    _check_single_evaluation_path(errors)
    _check_calibration_guard(errors)
    _check_governance(errors)
    return report(logger, "F-062", errors)


if __name__ == "__main__":
    sys.exit(main())
