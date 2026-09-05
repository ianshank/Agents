"""Gate-decision provenance and advisory gate rules.

One test per scenario in
``openspec/changes/add-gate-decision-provenance/specs/gate-decision-provenance/spec.md``.

Two properties carry the change and are asserted directly rather than inferred:

* the decision reaches the sinks (it is attached *before* they emit), and
* an advisory rule and a blocking rule reach the identical verdict on the
  identical run -- the single-evaluation-path invariant, without which a soak
  measures the soak rather than the scorer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from eval_harness.config.models import EvalConfig, GateConfig, GateRule
from eval_harness.core.interfaces import Scorer
from eval_harness.core.types import (
    EvalItem,
    GateDecision,
    ItemResult,
    RunContext,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.engine import EvalEngine
from eval_harness.gating import (
    GateResult,
    default_gate_evaluator,
    evaluate_gate,
    require_calibration_for_judge_gating,
)

SCORE = "acc"

#: A bound no score in [0, 1] can satisfy. Used where a test needs a rule to be
#: unmet regardless of what the target under test actually produced.
_UNSATISFIABLE = 1.1

#: The exact top-level keys a ``RunResult`` payload carried before this change.
#: Spelled out rather than derived so a future addition has to be a deliberate
#: edit here, not an accident that this test silently absorbs.
_PRE_CHANGE_PAYLOAD_KEYS = frozenset({"run_id", "config_name", "started_at", "finished_at", "aggregate", "items"})


def _run(mean: float = 0.4, *, pass_rate: float | None = None, items: list[ItemResult] | None = None) -> RunResult:
    """A completed run whose single scorer aggregate is *mean*."""
    now = datetime.now(UTC)
    return RunResult(
        run_id="run-1",
        config_name="cfg",
        items=items or [],
        aggregate={SCORE: ScoreAggregate(count=3, mean=mean, pass_rate=pass_rate if pass_rate is not None else mean)},
        started_at=now,
        finished_at=now,
    )


def _failing_item() -> ItemResult:
    """An item that failed before scoring, as ``item_error_policy='record'`` leaves it."""
    from eval_harness.core._execution_strategies import ITEM_ERROR_SCORE_NAME

    return ItemResult(
        item=EvalItem(id="i1", inputs={}),
        output=TargetOutput(output=None, error="boom"),
        scores=[ScoreResult(ITEM_ERROR_SCORE_NAME, value=0.0, passed=False)],
    )


# --------------------------------------------------------------------------
# Requirement: A run records its own gate decision
# --------------------------------------------------------------------------


def test_decision_reaches_the_sinks_before_they_emit() -> None:
    """Scenario: the decision reaches the sinks.

    The defect this change exists to fix: sinks fired in ``EvalEngine.run()``
    while the gate was evaluated afterwards in the CLI, so no exported artifact
    could carry a verdict. Asserting the sink *saw* it is the whole point --
    asserting only that ``run.gate`` is set afterwards would pass even if the
    attachment happened after the emit loop.
    """
    seen: list[GateDecision | None] = []

    class _RecordingSink:
        def emit(self, run: RunResult) -> None:
            seen.append(run.gate)

    config = EvalConfig.model_validate(
        {
            "schema_version": _schema_version(),
            "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {"q": "x"}, "expected": "x"}]}},
            "target": {"type": "echo"},
            "scorers": [{"type": "exact_match", "params": {"name": SCORE}}],
            "gate": {"rules": [{"score": SCORE, "min": 0.5}]},
        }
    )
    engine = EvalEngine.from_config(config)
    engine.sinks = [_RecordingSink()]  # type: ignore[list-item]
    run = engine.run()

    assert len(seen) == 1
    assert seen[0] is not None, "the sink emitted before the gate decision was attached"
    assert seen[0] is run.gate


def test_decision_names_what_it_measured() -> None:
    """Scenario: the decision names what it measured."""
    decision = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.9)]), _run(0.4)).to_decision()

    (record,) = decision.rules
    assert record.score == SCORE
    assert record.metric == "mean"
    assert record.observed == pytest.approx(0.4)
    assert record.minimum == pytest.approx(0.9)
    assert record.maximum is None
    assert record.met is False
    assert record.advisory is False


def test_no_gate_configured_leaves_the_payload_unchanged() -> None:
    """Scenario: no gate leaves the payload unchanged.

    ``gate=None`` must be omitted from the payload entirely, not emitted as a
    null -- the ADR 0031 obligation-4 contract ``diagnostics`` already holds.
    """
    payload = _run().to_dict()

    assert "gate" not in payload
    assert set(payload) == _PRE_CHANGE_PAYLOAD_KEYS
    assert default_gate_evaluator(None, _run()) is None


def test_configured_but_ruleless_gate_still_yields_a_decision() -> None:
    """A gate with no rules keeps its historical passing verdict.

    ``evaluate_gate`` has always returned ``passed=True`` for this shape, and
    the CLI has always printed ``QUALITY GATE: PASS`` on the strength of it.
    Folding it into the ``None`` case would silently drop that line for every
    config using the legacy ruleless-gate form.
    """
    decision = default_gate_evaluator(GateConfig(rules=[]), _run())

    assert decision is not None
    assert decision.passed is True
    assert decision.rules == []


def test_decision_is_serialised_into_the_payload() -> None:
    run = _run(0.4)
    run.gate = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.9)]), run).to_decision()

    emitted = run.to_dict()["gate"]

    assert emitted["passed"] is False
    assert emitted["blocking_failures"] == [f"{SCORE}.mean=0.400 below min 0.9"]
    assert emitted["advisory_failures"] == []
    assert emitted["rules"][0]["observed"] == pytest.approx(0.4)


# --------------------------------------------------------------------------
# Requirement: A gate rule can be declared advisory
# --------------------------------------------------------------------------


def test_report_only_defaults_to_false() -> None:
    """Scenario: the default reproduces existing behaviour."""
    assert GateRule(score=SCORE, min=0.5).report_only is False


def test_advisory_rule_without_a_bound_is_still_rejected() -> None:
    """Scenario: an advisory rule without a bound is still rejected.

    The flag changes where a verdict is filed, never whether one exists. A
    bound-less advisory rule is the same silent no-op the validator was written
    to catch, wearing a label.
    """
    with pytest.raises(ValueError, match="must set min, max, or both"):
        GateRule(score=SCORE, report_only=True)


# --------------------------------------------------------------------------
# Requirement: An advisory rule is evaluated identically and filed differently
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mean", [0.0, 0.4, 0.9, 1.0])
def test_advisory_and_blocking_agree_on_the_same_run(mean: float) -> None:
    """Scenario: advisory and blocking agree on the same run.

    The single-evaluation-path invariant, asserted over the boundary directly:
    the two configurations differ only in ``report_only``, so every field of
    the produced record except ``advisory`` must match. Two evaluation paths
    would let them drift, and the drift would be invisible during exactly the
    soak meant to establish trust in the threshold.
    """
    run = _run(mean)
    blocking = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.5)]), run)
    advisory = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.5, report_only=True)]), run)

    (b_record,) = blocking.rules
    (a_record,) = advisory.rules
    assert b_record.met == a_record.met
    assert b_record.observed == a_record.observed
    assert b_record.detail == a_record.detail
    assert b_record.advisory is False
    assert a_record.advisory is True


def test_failing_advisory_rule_does_not_fail_the_gate() -> None:
    """Scenario: a failing advisory rule does not fail the gate."""
    result = evaluate_gate(
        GateConfig(rules=[GateRule(score=SCORE, min=0.9, report_only=True), GateRule(score=SCORE, min=0.1)]),
        _run(0.4),
    )

    assert result.passed is True
    assert result.failures == []
    assert result.advisory == [f"{SCORE}.mean=0.400 below min 0.9"]


def test_advisory_rules_never_mask_a_blocking_failure() -> None:
    """Scenario: advisory rules never mask a blocking failure."""
    result = evaluate_gate(
        GateConfig(
            rules=[
                GateRule(score=SCORE, min=0.9, report_only=True),
                GateRule(score=SCORE, min=0.8),
            ]
        ),
        _run(0.4),
    )

    assert result.passed is False
    assert result.failures == [f"{SCORE}.mean=0.400 below min 0.8"]
    assert result.advisory == [f"{SCORE}.mean=0.400 below min 0.9"]


def test_a_soak_on_one_rule_leaves_the_others_live() -> None:
    """Scenario: a soak on one rule leaves the others live.

    This is the property that whole-gate exit-code neutralisation cannot
    provide, and the reason per-rule granularity exists.
    """
    result = evaluate_gate(
        GateConfig(
            rules=[
                GateRule(score=SCORE, min=0.99, report_only=True),  # uncalibrated, soaking
                GateRule(score=SCORE, min=0.5),  # calibrated, live
            ]
        ),
        _run(0.4),
    )

    assert result.passed is False, "the calibrated rule must still block"


def test_unevaluable_rule_records_a_null_observation() -> None:
    """A rule naming an absent score is 'could not measure', not 'measured zero'.

    Collapsing the two is how a gate comes to report a pass having measured
    nothing (ADR 0029).
    """
    result = evaluate_gate(GateConfig(rules=[GateRule(score="absent", min=0.5)]), _run())

    (record,) = result.rules
    assert record.observed is None
    assert record.met is False
    assert "not present in results" in record.detail


def test_advisory_outcomes_are_logged_without_borrowing_the_warning_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Advisory outcomes are visible, but never at the level blocking ones use.

    Emitting them at WARNING would train an operator to ignore a level that
    real failures also use.
    """
    with caplog.at_level(logging.INFO, logger="eval_harness.gating"):
        evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.9, report_only=True)]), _run(0.4))

    advisory_records = [r for r in caplog.records if "advisory" in r.getMessage()]
    assert advisory_records, "an unmet advisory rule must be logged"
    assert all(r.levelno == logging.INFO for r in advisory_records)


# --------------------------------------------------------------------------
# Sample-reduction failures follow the gate's own blocking posture
# --------------------------------------------------------------------------


def test_sample_reduction_blocks_when_any_rule_can_block() -> None:
    run = _run(0.9, items=[_failing_item()])
    result = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.1)]), run)

    assert result.passed is False
    assert any("failed before scoring" in f for f in result.failures)


def test_sample_reduction_is_advisory_when_no_rule_can_block() -> None:
    """An all-advisory gate must not start failing runs on sample reduction.

    Its whole point is not to block; blocking on a data-integrity warning would
    make the advisory configuration stricter than the blocking one.
    """
    run = _run(0.9, items=[_failing_item()])
    result = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.1, report_only=True)]), run)

    assert result.passed is True
    assert any("failed before scoring" in a for a in result.advisory)


# --------------------------------------------------------------------------
# Requirement: an advisory rule is not gating for the calibration guard
# --------------------------------------------------------------------------


class _JudgeBackedScorer(Scorer):
    """A scorer whose verdict depends on a judge.

    Implements the real protocol rather than duck-typing a partial stand-in:
    the guard resolves ``.name``/``.uses_judge()`` off the *constructed*
    scorer, so a stub that is not actually a scorer would exercise a different
    call than production makes.
    """

    default_name = "judged"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        return ScoreResult(self.name, value=1.0, passed=True)

    def uses_judge(self) -> bool:
        return True


def _schema_version() -> str:
    from eval_harness.version import SCHEMA_VERSION

    return SCHEMA_VERSION


def _config_with_rule(**rule: Any) -> EvalConfig:
    return EvalConfig.model_validate(
        {
            "schema_version": _schema_version(),
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "gate": {"rules": [{"score": "judged", **rule}]},
        }
    )


def test_advisory_judge_rule_is_accepted_without_a_calibration_artifact() -> None:
    """Scenario: a judge-backed scorer may be measured without a calibration artifact.

    Requiring the artifact before the judge may be *measured* makes calibration
    unreachable: the labelled corpus that produces the artifact is assembled
    from exactly these advisory runs.
    """
    require_calibration_for_judge_gating(_config_with_rule(min=0.5, report_only=True), [_JudgeBackedScorer()])


def test_blocking_judge_rule_is_still_refused_without_a_calibration_artifact() -> None:
    """Scenario: the fail-closed refusal is unchanged for blocking rules."""
    with pytest.raises(ValueError, match="judge_calibration"):
        require_calibration_for_judge_gating(_config_with_rule(min=0.5), [_JudgeBackedScorer()])


def test_other_advisory_rules_do_not_soften_the_refusal() -> None:
    config = EvalConfig.model_validate(
        {
            "schema_version": _schema_version(),
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "gate": {
                "rules": [
                    {"score": "judged", "min": 0.5, "report_only": True},
                    {"score": "judged", "min": 0.6},
                ]
            },
        }
    )
    with pytest.raises(ValueError, match="judge_calibration"):
        require_calibration_for_judge_gating(config, [_JudgeBackedScorer()])


def test_promotion_to_blocking_re_arms_the_requirement() -> None:
    """Scenario: promotion to blocking re-arms the requirement."""
    scorers = [_JudgeBackedScorer()]
    require_calibration_for_judge_gating(_config_with_rule(min=0.5, report_only=True), scorers)

    with pytest.raises(ValueError, match="judge_calibration"):
        require_calibration_for_judge_gating(_config_with_rule(min=0.5), scorers)


# --------------------------------------------------------------------------
# The injected seam
# --------------------------------------------------------------------------


def test_gate_evaluator_is_injectable() -> None:
    """The engine reaches its verdict through a seam, not a hardcoded call.

    A caller can supply a different policy without the engine growing a second
    code path for it.
    """
    sentinel = GateDecision(passed=False, blocking_failures=["stub"])
    config = EvalConfig.model_validate(
        {
            "schema_version": _schema_version(),
            "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {"q": "x"}, "expected": "x"}]}},
            "target": {"type": "echo"},
            "scorers": [{"type": "exact_match", "params": {"name": SCORE}}],
        }
    )
    engine = EvalEngine.from_config(config)
    engine.gate_evaluator = lambda gate, run: sentinel

    assert engine.run().gate is sentinel


def test_gate_result_to_decision_round_trips_every_channel() -> None:
    result = GateResult(passed=False, failures=["b"], advisory=["a"])
    decision = result.to_decision()

    assert decision.passed is False
    assert decision.blocking_failures == ["b"]
    assert decision.advisory_failures == ["a"]
    # Copies, not aliases: mutating the source must not rewrite a recorded decision.
    result.failures.append("late")
    assert decision.blocking_failures == ["b"]


# --------------------------------------------------------------------------
# Requirement: advisory outcomes do not change the process exit code
# --------------------------------------------------------------------------


def _write_config(tmp_path: Any, rules: list[dict[str, Any]]) -> str:
    import yaml

    cfg = {
        "schema_version": _schema_version(),
        "run": {"name": "gate-provenance"},
        "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {"q": "x"}, "expected": "x"}]}},
        "target": {"type": "echo"},
        "scorers": [{"type": "exact_match", "params": {"name": SCORE}}],
        "gate": {"rules": rules},
    }
    path = tmp_path / "eval.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def test_cli_exits_zero_when_only_advisory_rules_are_unmet(tmp_path: Any, capsys: Any) -> None:
    """Scenario: an unmet advisory rule exits zero.

    A CI job that reads a non-zero exit as "blocked" must keep that meaning
    exactly.
    """
    from eval_harness.cli import main

    # A deliberately unsatisfiable bound: no score in [0,1] can reach it, so the
    # rule is unmet whatever the echo target happens to produce. The test is about
    # the exit code, not about the target.
    config = _write_config(tmp_path, [{"score": SCORE, "min": _UNSATISFIABLE, "report_only": True}])
    rc = main(["run", "--config", config, "--offline"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "QUALITY GATE: PASS" in out
    assert "advisory, non-blocking" in out


def test_cli_exits_non_zero_when_a_blocking_rule_is_unmet(tmp_path: Any, capsys: Any) -> None:
    """Scenario: advisory reporting never masks a blocking failure."""
    from eval_harness.cli import main

    rc = main(
        [
            "run",
            "--config",
            _write_config(
                tmp_path,
                [
                    {"score": SCORE, "min": _UNSATISFIABLE, "report_only": True},
                    {"score": SCORE, "min": _UNSATISFIABLE},
                ],
            ),
            "--offline",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "QUALITY GATE: FAIL" in out
    # The blocking failure is reported in its own section, not subordinated to
    # the advisory one.
    assert out.index("QUALITY GATE: FAIL") < out.index(f"  - {SCORE}.mean")


def test_cli_exit_code_and_recorded_decision_come_from_one_evaluation(tmp_path: Any) -> None:
    """Scenario: the exit code still follows the decision.

    Asserted by construction: the CLI reads ``run.gate`` rather than calling
    ``evaluate_gate`` itself, so there is only one evaluation to disagree with.
    """
    import eval_harness.cli as cli

    assert not hasattr(cli, "evaluate_gate"), (
        "the CLI must not re-evaluate the gate: two evaluations could let the exported "
        "artifact and the exit code disagree"
    )


# --------------------------------------------------------------------------
# The reporting artifact carries the verdict
# --------------------------------------------------------------------------


def _decision(*, passed: bool, advisory: bool) -> GateDecision:
    from eval_harness.core.types import GateRuleRecord

    return GateDecision(
        passed=passed,
        blocking_failures=[] if advisory else ["blocked"],
        advisory_failures=["soaking"] if advisory else [],
        rules=[
            GateRuleRecord(
                score=SCORE,
                metric="mean",
                observed=0.4,
                minimum=0.9,
                maximum=None,
                met=False,
                advisory=advisory,
                detail="detail",
            )
        ],
    )


def test_html_report_renders_the_gate_verdict(tmp_path: Any) -> None:
    """The reason this change exists: the report can now state the verdict.

    Before the decision was carried on ``RunResult`` this artifact could show a
    run's scores and never say whether the gate passed.
    """
    from eval_harness.sinks import HtmlFileSink

    run = _run(0.4)
    run.gate = _decision(passed=False, advisory=False)
    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(run)

    assert "Quality gate — FAIL" in html
    assert "unmet (blocking)" in html


def test_html_report_distinguishes_advisory_from_blocking(tmp_path: Any) -> None:
    """A soak whose advisory outcomes are invisible in the artifact is not a soak."""
    from eval_harness.sinks import HtmlFileSink

    run = _run(0.4)
    run.gate = _decision(passed=True, advisory=True)
    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(run)

    assert "Quality gate — PASS" in html
    assert "unmet (advisory)" in html
    assert "unmet (blocking)" not in html


def test_html_report_is_unchanged_for_an_ungated_run(tmp_path: Any) -> None:
    """No gate configured renders exactly the markup it always did."""
    from eval_harness.sinks import HtmlFileSink

    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(_run(0.4))

    assert "Quality gate" not in html


def test_html_report_explains_a_failure_that_belongs_to_no_rule(tmp_path: Any) -> None:
    """A FAIL whose cause is not a rule must still be explained in the artifact.

    Regression test for a defect found in review: ``_item_error_failures``
    refuses to gate over a sample reduced by item errors, and that verdict has
    no ``GateRuleRecord`` behind it. Rendering only rule rows produced a report
    captioned FAIL in which every row read "met" -- an unexplained verdict,
    which is the same incomplete-provenance defect this capability exists to
    remove.
    """
    from eval_harness.sinks import HtmlFileSink

    run = _run(0.9, items=[_failing_item()])
    # The rule is satisfied; the run fails only on the reduced sample.
    run.gate = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.1)]), run).to_decision()
    assert run.gate.passed is False
    assert all(rule.met for rule in run.gate.rules), "precondition: every rule row reads 'met'"

    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(run)

    assert "Quality gate — FAIL" in html
    assert "Gate-level findings" in html
    assert "failed before scoring" in html


def test_html_report_does_not_duplicate_a_rule_failure(tmp_path: Any) -> None:
    """A failure already shown as a rule row is not repeated below the table."""
    from eval_harness.sinks import HtmlFileSink

    run = _run(0.4)
    run.gate = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.9)]), run).to_decision()
    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(run)

    assert "unmet (blocking)" in html
    assert "Gate-level findings" not in html


def test_html_report_labels_an_advisory_gate_level_finding(tmp_path: Any) -> None:
    """An all-advisory gate files sample reduction as advisory, and says so."""
    from eval_harness.sinks import HtmlFileSink

    run = _run(0.9, items=[_failing_item()])
    run.gate = evaluate_gate(GateConfig(rules=[GateRule(score=SCORE, min=0.1, report_only=True)]), run).to_decision()
    assert run.gate.passed is True

    html = HtmlFileSink(path=str(tmp_path / "r.html")).render(run)

    assert "Quality gate — PASS" in html
    assert "advisory:" in html
    assert "failed before scoring" in html
