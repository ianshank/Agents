"""Item-failure semantics: a target that raises must never vanish from a run.

Before this module's feature, ``max_workers`` silently decided failure semantics:
the sequential path propagated a target exception and aborted the run, while the
parallel path caught it and dropped the item from ``RunResult.items`` entirely.
With ``fail_fast=False`` (the default) that produced a run reporting
``pass_rate=1.0`` over a silently reduced denominator, with no record of the
failure in ``items``, ``aggregate``, ``diagnostics`` or ``to_dict()`` — the
harness's own stated invariant, written down for the state-adapter lifecycle
("the item always gets a normal, visibly-failed result, never silently
dropped"), violated in the one place it mattered most.

``RunSettings.item_error_policy`` now owns that decision and ``max_workers``
owns none of it, so the two execution paths agree. The tests below are written
as *equivalence* assertions wherever possible: the missing oracle was never
"is the parallel path covered" (both branches were) but "do the two paths agree
when something fails".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

import pytest
from pydantic import ValidationError

from eval_harness.config import load_config_dict
from eval_harness.config.models import RunSettings
from eval_harness.core._execution_strategies import (
    ITEM_ERROR_POLICY_RECORD as RECORD,
)
from eval_harness.core._execution_strategies import ITEM_ERROR_SCORE_NAME
from eval_harness.core.interfaces import StateResetError
from eval_harness.core.types import EvalItem, ItemResult, RunResult, ScoreResult, TargetOutput
from eval_harness.engine import EvalEngine
from eval_harness.gating import GateResult, evaluate_gate
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.version import SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Test targets, registered once under names this module owns.
#
# Registered rather than constructed directly so the tests exercise the same
# resolution path the real engine uses (AGENTS.md "Testing conventions"). The
# registry has no unregister hook, so registration happens once at import under
# names namespaced to this module rather than per-test.
# ---------------------------------------------------------------------------

RAISING_TARGET = "_test_raising_target"
RESET_ERROR_TARGET = "_test_state_reset_target"

#: Item id whose target raises. Deliberately not the first or last item, so a
#: failure landing in the wrong result slot is visible in ordering assertions.
FAILING_ITEM_ID = "2"

#: The message the raising target fails with; asserted verbatim so the test
#: proves the *cause* is carried through to the result, not merely that some
#: error was recorded.
BOOM = "upstream 500 from the model provider"


class _RaisingTarget:
    """Fails on exactly one item id and echoes every other item.

    Mirrors the realistic case: a custom ``TargetRunner`` (the published
    Protocol says nothing about exceptions, so raising is a legitimate
    implementation) that fails intermittently rather than uniformly.
    """

    def __init__(self, fail_on: str = FAILING_ITEM_ID, message: str = BOOM) -> None:
        self.fail_on = fail_on
        self.message = message

    def run(self, item: EvalItem) -> TargetOutput:
        if item.id == self.fail_on:
            raise RuntimeError(self.message)
        return TargetOutput(output=item.inputs.get("q"))

    def is_deterministic(self) -> bool:
        return True


class _StateResetErrorTarget:
    """Raises the one exception that must abort a run under every policy."""

    def run(self, item: EvalItem) -> TargetOutput:
        raise StateResetError(f"item {item.id!r}: state reset failed")

    def is_deterministic(self) -> bool:
        return True


bootstrap()
TARGETS.register_class(RAISING_TARGET, _RaisingTarget)
TARGETS.register_class(RESET_ERROR_TARGET, _StateResetErrorTarget)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

N_ITEMS = 5


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _config(
    *,
    target: str = RAISING_TARGET,
    target_params: dict | None = None,
    **run_overrides: object,
) -> dict:
    """A minimal config whose only variable is the run block under test."""
    run: dict[str, object] = {"name": "t", "run_id": "fixed-iep", "seed": 42}
    run.update(run_overrides)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "dataset": {
            "type": "inline",
            "params": {
                "items": [{"id": str(i), "inputs": {"q": f"q{i}"}, "expected": f"q{i}"} for i in range(N_ITEMS)]
            },
        },
        "target": {"type": target, "params": target_params or {}},
        "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
        "sinks": [],
    }


def _run(**overrides: object) -> RunResult:
    """Build an engine from a config dict and run it."""
    cfg_dict = _config(**overrides)  # type: ignore[arg-type]
    engine: EvalEngine = EvalEngine.from_config(load_config_dict(cfg_dict), langfuse_client=NullLangfuseClient())
    engine.clock = _fixed_clock
    # Bound to a typed local first: EvalEngine.run is @observe()-decorated, so
    # its return type erases to Any at the call site.
    result: RunResult = engine.run()
    return result


def _scores_by_name(item_result: ItemResult) -> dict[str, ScoreResult]:
    return {s.name: s for s in item_result.scores}


# ---------------------------------------------------------------------------
# 1. The defect itself: a failed item must stay in the run
# ---------------------------------------------------------------------------


class TestFailedItemIsRecorded:
    """Under the default policy a raising target yields a visibly-failed item."""

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_item_survives_in_results(self, max_workers: int) -> None:
        run = _run(max_workers=max_workers, item_error_policy=RECORD)

        assert len(run.items) == N_ITEMS, "the failed item was dropped from the run"
        assert [ir.item.id for ir in run.items] == [str(i) for i in range(N_ITEMS)]

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_failure_cause_is_carried_on_the_result(self, max_workers: int) -> None:
        run = _run(max_workers=max_workers, item_error_policy=RECORD)
        failed = next(ir for ir in run.items if ir.item.id == FAILING_ITEM_ID)

        assert failed.output.output is None
        assert failed.output.error is not None
        assert BOOM in failed.output.error

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_failure_is_scored_as_a_failure(self, max_workers: int) -> None:
        run = _run(max_workers=max_workers, item_error_policy=RECORD)
        failed = next(ir for ir in run.items if ir.item.id == FAILING_ITEM_ID)
        score = _scores_by_name(failed)[ITEM_ERROR_SCORE_NAME]

        assert score.passed is False
        assert score.value == RunSettings().item_error_score
        assert BOOM in (score.comment or "")

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_failed_item_stays_in_the_aggregate_denominator(self, max_workers: int) -> None:
        """The inflation bug: pass_rate must not be computed over survivors only."""
        run = _run(max_workers=max_workers, item_error_policy=RECORD)
        agg = run.aggregate[ITEM_ERROR_SCORE_NAME]

        assert agg.count == 1
        assert agg.pass_rate == 0.0

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_degraded_denominator_is_flagged_as_a_run_diagnostic(self, max_workers: int) -> None:
        """The failed item's scorers never ran, so every OTHER score's aggregate
        covers fewer attempts than the run holds. A gate rule naming one of those
        other scores would not otherwise see it."""
        run = _run(max_workers=max_workers, item_error_policy=RECORD)
        codes = [d["code"] for d in run.diagnostics]

        assert "item_execution_failures" in codes
        message = next(d["message"] for d in run.diagnostics if d["code"] == "item_execution_failures")
        assert f"1 of {N_ITEMS}" in message

        payload = run.to_dict()
        assert any(d["code"] == "item_execution_failures" for d in payload["reliability"]["diagnostics"])

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_failure_reaches_the_serialized_payload(self, max_workers: int) -> None:
        """Sinks and Langfuse see the failure, not just the log stream."""
        payload = _run(max_workers=max_workers, item_error_policy=RECORD).to_dict()
        entry = next(i for i in payload["items"] if i["id"] == FAILING_ITEM_ID)

        assert entry["error"] is not None
        assert BOOM in entry["error"]
        assert any(s["name"] == ITEM_ERROR_SCORE_NAME and s["passed"] is False for s in entry["scores"])


# ---------------------------------------------------------------------------
# 2. The missing oracle: the two execution paths must agree on failure
# ---------------------------------------------------------------------------


class TestSequentialParallelEquivalenceUnderFailure:
    """``max_workers`` must not change what a run reports when an item fails.

    The pre-existing equivalence test asserted exactly this property but ran on
    an all-passing dataset, so it could never observe the divergence.
    """

    def test_same_items_and_aggregate(self) -> None:
        seq = _run(max_workers=1, item_error_policy=RECORD)
        par = _run(max_workers=4, item_error_policy=RECORD)

        assert [ir.item.id for ir in seq.items] == [ir.item.id for ir in par.items]
        assert set(seq.aggregate) == set(par.aggregate)
        for name, agg in seq.aggregate.items():
            assert agg.count == par.aggregate[name].count
            assert agg.pass_rate == par.aggregate[name].pass_rate
            assert agg.mean == pytest.approx(par.aggregate[name].mean)

    def test_same_serialized_items(self) -> None:
        seq_items = _run(max_workers=1, item_error_policy=RECORD).to_dict()["items"]
        par_items = _run(max_workers=4, item_error_policy=RECORD).to_dict()["items"]

        # latency_ms is wall-clock and legitimately differs between paths.
        def _stable(entries: list[dict]) -> list[dict]:
            return [{k: v for k, v in e.items() if k != "latency_ms"} for e in entries]

        assert _stable(seq_items) == _stable(par_items)


# ---------------------------------------------------------------------------
# 3. The 'raise' policy and fail_fast keep aborting
# ---------------------------------------------------------------------------


class TestRaisePolicy:
    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_policy_raise_aborts_the_run(self, max_workers: int) -> None:
        with pytest.raises(RuntimeError, match=BOOM):
            _run(max_workers=max_workers, item_error_policy="raise")

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_fail_fast_still_aborts_under_the_record_policy(self, max_workers: int) -> None:
        """``fail_fast`` outranks the policy — it is the stronger statement."""
        with pytest.raises(RuntimeError, match=BOOM):
            _run(max_workers=max_workers, fail_fast=True, item_error_policy="record")

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_state_reset_error_always_propagates(self, max_workers: int) -> None:
        """Never policy-gated: continuing risks scoring against dirty state."""
        with pytest.raises(StateResetError):
            _run(max_workers=max_workers, target=RESET_ERROR_TARGET, item_error_policy="record")


# ---------------------------------------------------------------------------
# 4. Repeated attempts keep their attempt identity when they fail
# ---------------------------------------------------------------------------


class TestRepeatedAttempts:
    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_every_attempt_of_a_failing_item_is_recorded(self, max_workers: int) -> None:
        repetitions = 3
        run = _run(max_workers=max_workers, repetitions=repetitions, item_error_policy=RECORD)

        assert len(run.items) == N_ITEMS * repetitions
        failed = [ir for ir in run.items if ir.item.id == FAILING_ITEM_ID]
        assert len(failed) == repetitions
        # Every attempt of a failing item carries its own identity, so the set of
        # attempt indices must be complete -- not merely the right length.
        assert sorted(ir.attempt_index for ir in failed if ir.attempt_index is not None) == list(range(repetitions))
        for ir in failed:
            assert ir.attempt_id == f"{FAILING_ITEM_ID}:{ir.attempt_index}"
            assert ir.item_run_id is not None


# ---------------------------------------------------------------------------
# 5. Configuration is data, not a literal at a call site
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_default_policy_raises(self) -> None:
        """The safe default. Recording by default turned the sequential path's
        hard abort into a completed run that a gate could pass -- a regression
        against the behaviour this feature was meant to protect."""
        assert RunSettings().item_error_policy == "raise"

    def test_default_error_score_is_a_declared_field(self) -> None:
        assert RunSettings().item_error_score == 0.0

    def test_error_score_is_configurable(self) -> None:
        run = _run(max_workers=4, item_error_score=0.25, item_error_policy=RECORD)
        failed = next(ir for ir in run.items if ir.item.id == FAILING_ITEM_ID)

        assert _scores_by_name(failed)[ITEM_ERROR_SCORE_NAME].value == 0.25

    def test_unknown_policy_is_rejected(self) -> None:
        """The field is a Literal, so an unknown policy fails validation rather
        than silently falling through to the permissive branch at runtime."""
        with pytest.raises(ValidationError):
            RunSettings(item_error_policy="ignore")  # type: ignore[arg-type]

    def test_out_of_range_error_score_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RunSettings(item_error_score=1.5)

    def test_existing_configs_keep_working(self) -> None:
        """The new fields are optional; a config predating them still loads."""
        cfg = load_config_dict(_config(target="echo", target_params={"output_key": "q"}))

        assert cfg.run.item_error_policy == "raise"
        assert cfg.run.item_error_score == 0.0


# ---------------------------------------------------------------------------
# 6. Backwards compatibility: a clean run is unchanged
# ---------------------------------------------------------------------------


class TestCleanRunIsUnchanged:
    """No failure means no new keys, no new scores, no behaviour change."""

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_no_error_score_appears_when_nothing_fails(self, max_workers: int) -> None:
        run = _run(max_workers=max_workers, target="echo", target_params={"output_key": "q"})

        assert len(run.items) == N_ITEMS
        assert ITEM_ERROR_SCORE_NAME not in run.aggregate
        for ir in run.items:
            assert ITEM_ERROR_SCORE_NAME not in _scores_by_name(ir)
            assert ir.output.error is None

    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_no_diagnostic_and_no_reliability_key_on_a_clean_run(self, max_workers: int) -> None:
        """ADR 0031 obligation 4: a clean run's payload is unchanged."""
        run = _run(max_workers=max_workers, target="echo", target_params={"output_key": "q"})

        assert run.diagnostics == []
        assert "reliability" not in run.to_dict()


# ---------------------------------------------------------------------------
# 7. Observability
# ---------------------------------------------------------------------------


class TestLogging:
    @pytest.mark.parametrize("max_workers", [1, 4])
    def test_recorded_failure_is_logged_with_the_item_id(
        self, max_workers: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("ERROR", logger="eval_harness"):
            _run(max_workers=max_workers, item_error_policy=RECORD)

        assert any(FAILING_ITEM_ID in rec.getMessage() and BOOM in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# 8. The gate: the assertion whose absence let the original defect ship
# ---------------------------------------------------------------------------


class TestGateSeesItemFailures:
    """A gate must not read a healthy rate over a sample it does not know shrank.

    The first version of this feature recorded the failed item and stopped
    there. Its own scorers never ran, so ``acc.count`` was 3 of 4 and a rule on
    ``acc.pass_rate`` still read 1.0 and passed -- the exact outcome the change
    was written to prevent. Every test in this module asserted on ``items``,
    ``aggregate`` and ``diagnostics``; not one called ``evaluate_gate``, which
    is precisely why it shipped.
    """

    RULE: ClassVar[dict[str, object]] = {"score": "acc", "metric": "pass_rate", "min": 0.9}

    def _gated(self, *, policy: str, allow: bool | None = None) -> GateResult:
        gate: dict[str, object] = {"rules": [self.RULE]}
        if allow is not None:
            gate["allow_item_errors"] = allow
        cfg_dict = _config(max_workers=4, item_error_policy=policy)
        cfg_dict["gate"] = gate
        config = load_config_dict(cfg_dict)
        engine: EvalEngine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        engine.clock = _fixed_clock
        run: RunResult = engine.run()
        return evaluate_gate(config.gate, run)

    def test_gate_fails_when_an_item_never_reached_the_scorers(self) -> None:
        result = self._gated(policy=RECORD)

        assert result.passed is False
        assert any("failed before scoring" in f for f in result.failures)

    def test_the_failure_names_the_reduced_sample(self) -> None:
        """An operator has to be able to tell this apart from a real quality drop."""
        result = self._gated(policy=RECORD)
        message = next(f for f in result.failures if "failed before scoring" in f)

        assert f"1 of {N_ITEMS}" in message
        assert "allow_item_errors" in message

    def test_allow_item_errors_is_an_explicit_opt_in(self) -> None:
        """Gating over a partial run stays possible -- but only on purpose."""
        result = self._gated(policy=RECORD, allow=True)

        assert result.passed is True

    def test_a_clean_run_is_unaffected_by_the_guard(self) -> None:
        cfg_dict = _config(max_workers=4, target="echo", target_params={"output_key": "q"})
        cfg_dict["gate"] = {"rules": [self.RULE]}
        config = load_config_dict(cfg_dict)
        engine: EvalEngine = EvalEngine.from_config(config, langfuse_client=NullLangfuseClient())
        engine.clock = _fixed_clock

        assert evaluate_gate(config.gate, engine.run()).passed is True

    def test_default_policy_never_reaches_the_gate_at_all(self) -> None:
        """Under 'raise' the run aborts, so there is no misleading artefact to gate."""
        with pytest.raises(RuntimeError, match=BOOM):
            self._gated(policy="raise")
