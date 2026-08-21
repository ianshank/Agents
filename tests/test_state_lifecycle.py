"""Tests for the state-adapter engine lifecycle (Group 2, add-stateful-outcome-evaluation).

Covers ``reset -> snapshot(before) -> target.run -> snapshot(after) -> evaluate``
wiring in ``EvalEngine._run_one`` / ``core/_state_lifecycle.py``: ordering, the
two divergent failure semantics (``StateResetError`` aborts the run
unconditionally; a snapshot/evaluate failure fails just the item), no leakage
across ``repetitions > 1`` attempts, and the concurrency lock. The no-adapter
path (byte-identical behaviour) is covered by the existing ``test_engine.py``
and ``test_repeated_attempts.py`` suites, deliberately left untouched.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

from eval_harness.config import load_config_dict
from eval_harness.core.interfaces import StateResetError
from eval_harness.core.types import EvalItem, RunContext, ScoreResult, StateEvaluation, StateSnapshot, TargetOutput
from eval_harness.engine import EvalEngine
from eval_harness.version import SCHEMA_VERSION


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=UTC)


def _config(n_items=3, extra_run=None):
    run = {"name": "t", "run_id": "fixed-state", "seed": 7}
    if extra_run:
        run.update(extra_run)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "dataset": {
            "type": "inline",
            "params": {"items": [{"id": str(i), "inputs": {"q": f"q{i}"}, "expected": f"q{i}"} for i in range(n_items)]},
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
        "sinks": [],
    }


def _engine(cfg, state_adapter=None):
    config = load_config_dict(cfg)
    engine = EvalEngine.from_config(config)
    engine.clock = _fixed_clock
    engine.state_adapter = state_adapter
    return engine


class _RecordingAdapter:
    """Logs every call, in order, with a per-instance sequence counter."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._n = 0

    def reset(self, ctx: RunContext) -> None:
        self._n = 0
        self.calls.append("reset")

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        self._n += 1
        self.calls.append(f"snapshot:{self._n}")
        return StateSnapshot(data={"n": self._n})

    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
        self.calls.append("evaluate")
        return StateEvaluation(goal_reached=after.data["n"] > before.data["n"])


class _FailingResetAdapter:
    def __init__(self) -> None:
        self.reset_calls = 0

    def reset(self, ctx: RunContext) -> None:
        self.reset_calls += 1
        raise RuntimeError("reset backend unavailable")

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        raise AssertionError("snapshot must not be reached when reset fails")

    def evaluate(self, *, item, before, after) -> StateEvaluation:
        raise AssertionError("evaluate must not be reached when reset fails")


class _FailingSnapshotAdapter:
    """Fails on the *second* snapshot call (the "after" capture) so the "before"
    capture, and thus target.run, still happen -- exercising the after/evaluate
    branch distinctly from a before-snapshot failure."""

    def __init__(self, fail_on_call: int = 2) -> None:
        self.fail_on_call = fail_on_call
        self._n = 0

    def reset(self, ctx: RunContext) -> None:
        self._n = 0

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        self._n += 1
        if self._n == self.fail_on_call:
            raise RuntimeError(f"snapshot backend timeout on call {self._n}")
        return StateSnapshot(data={"n": self._n})

    def evaluate(self, *, item, before, after) -> StateEvaluation:
        return StateEvaluation(goal_reached=True)


class _FailingEvaluateAdapter:
    def reset(self, ctx: RunContext) -> None:
        pass

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        return StateSnapshot(data={})

    def evaluate(self, *, item, before, after) -> StateEvaluation:
        raise RuntimeError("evaluate crashed")


class _CountingTargetThatFailsOnce:
    """Raises on its first call, succeeds thereafter -- proves reset for a later
    attempt does not depend on an earlier attempt's target having succeeded."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, item: EvalItem) -> TargetOutput:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("target outage on first call")
        return TargetOutput(output=item.inputs["q"])

    def is_deterministic(self) -> bool | None:
        return None


class _InterleavingProbeTarget:
    """Detects concurrent entry: if two threads are ever inside `run` at the
    same time, `overlap_detected` flips true. A short sleep widens the window a
    race would need to land in."""

    def __init__(self) -> None:
        self._active = 0
        self._guard = threading.Lock()
        self.overlap_detected = False
        self.max_concurrent = 0

    def run(self, item: EvalItem) -> TargetOutput:
        with self._guard:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
            if self._active > 1:
                self.overlap_detected = True
        time.sleep(0.01)
        with self._guard:
            self._active -= 1
        return TargetOutput(output=item.id)

    def is_deterministic(self) -> bool | None:
        return None


class _ThreadSafeRecordingAdapter(_RecordingAdapter):
    """Same recording contract, but with its own lock around bookkeeping --
    proves the *engine's* lock is what serializes calls, not luck."""

    def __init__(self) -> None:
        super().__init__()
        self._bookkeeping_lock = threading.Lock()

    def reset(self, ctx: RunContext) -> None:
        with self._bookkeeping_lock:
            super().reset(ctx)

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        with self._bookkeeping_lock:
            return super().snapshot(ctx)

    def evaluate(self, *, item, before, after) -> StateEvaluation:
        with self._bookkeeping_lock:
            return super().evaluate(item=item, before=before, after=after)


class TestLifecycleOrdering:
    def test_reset_snapshot_run_snapshot_evaluate_in_order(self):
        adapter = _RecordingAdapter()
        engine = _engine(_config(n_items=1), state_adapter=adapter)
        engine.run()
        assert adapter.calls == ["reset", "snapshot:1", "snapshot:2", "evaluate"]

    def test_state_evaluation_reaches_the_scorer_context(self):
        """Decision A: ctx.extra is the handoff -- the future state scorers (Group 3)
        read StateEvaluation from here, not a new EvalEngine field."""
        captured: dict[str, StateEvaluation] = {}

        class _CapturingScorer:
            name = "capture"

            def score(self, item, output, ctx):
                captured["evaluation"] = ctx.extra.get("state_evaluation")
                return ScoreResult(self.name, value=1.0, passed=True)

            def uses_judge(self) -> bool:
                return False

        adapter = _RecordingAdapter()
        engine = _engine(_config(n_items=1), state_adapter=adapter)
        engine.scorers = [_CapturingScorer()]
        engine.run()
        assert isinstance(captured["evaluation"], StateEvaluation)
        assert captured["evaluation"].goal_reached is True

    def test_no_adapter_configured_never_touches_ctx_extra(self):
        engine = _engine(_config(n_items=1))
        result = engine.run()
        assert result.items[0].scores  # sanity: the run still scored normally


class TestResetFailureAbortsTheRun:
    def test_sequential_reset_failure_propagates_and_produces_no_item_result(self):
        adapter = _FailingResetAdapter()
        engine = _engine(_config(n_items=2))
        engine.state_adapter = adapter
        with pytest.raises(StateResetError, match="state reset failed"):
            engine.run()
        assert adapter.reset_calls == 1  # aborted on the very first attempt

    def test_reset_failure_aborts_even_when_fail_fast_is_false(self):
        """The one engine failure path that is never fail_fast-gated."""
        adapter = _FailingResetAdapter()
        engine = _engine(_config(n_items=2, extra_run={"fail_fast": False}))
        engine.state_adapter = adapter
        with pytest.raises(StateResetError):
            engine.run()

    def test_parallel_reset_failure_propagates_and_shuts_down_the_pool(self):
        adapter = _FailingResetAdapter()
        engine = _engine(_config(n_items=6, extra_run={"max_workers": 3, "fail_fast": False}))
        engine.state_adapter = adapter
        with pytest.raises(StateResetError):
            engine.run()

    def test_reset_runs_again_for_the_next_attempt_even_after_a_target_failure(self):
        """A target failure (unrelated to the adapter) must not skip the next
        attempt's reset -- reset is per-attempt, not gated on prior success."""
        adapter = _RecordingAdapter()
        engine = _engine(_config(n_items=2))
        engine.target = _CountingTargetThatFailsOnce()
        engine.state_adapter = adapter
        with pytest.raises(RuntimeError, match="target outage"):
            # Sequential path: an uncaught target error aborts run() immediately,
            # same as it always has -- this only proves reset ran once before that.
            engine.run()
        assert adapter.calls.count("reset") == 1


class TestSnapshotOrEvaluateFailureFailsJustTheItem:
    def test_after_snapshot_failure_produces_a_visible_failing_item_not_a_dropped_one(self):
        adapter = _FailingSnapshotAdapter(fail_on_call=2)
        engine = _engine(_config(n_items=1))
        engine.state_adapter = adapter
        result = engine.run()
        assert len(result.items) == 1  # never silently dropped
        state_scores = [s for s in result.items[0].scores if s.name == "state_lifecycle"]
        assert len(state_scores) == 1
        assert state_scores[0].passed is False
        assert "snapshot(after)/evaluate failed" in state_scores[0].comment

    def test_evaluate_failure_produces_a_visible_failing_item(self):
        engine = _engine(_config(n_items=1))
        engine.state_adapter = _FailingEvaluateAdapter()
        result = engine.run()
        assert len(result.items) == 1
        state_scores = [s for s in result.items[0].scores if s.name == "state_lifecycle"]
        assert state_scores[0].passed is False
        assert "snapshot(after)/evaluate failed" in state_scores[0].comment

    def test_before_snapshot_failure_still_runs_the_target_and_produces_a_result(self):
        adapter = _FailingSnapshotAdapter(fail_on_call=1)
        engine = _engine(_config(n_items=1))
        engine.state_adapter = adapter
        result = engine.run()
        assert len(result.items) == 1
        assert result.items[0].output.output == "q0"  # target still ran normally
        state_scores = [s for s in result.items[0].scores if s.name == "state_lifecycle"]
        assert "snapshot(before) failed" in state_scores[0].comment

    def test_state_failure_gates_judges_like_any_other_programmatic_failure(self):
        """F-057's routing rule extended to state failures: a judge never runs
        once the item is already known to have failed."""

        class _JudgeScorer:
            name = "quality"

            def score(self, item, output, ctx):  # pragma: no cover - must never be called
                raise AssertionError("judge scorer must be skipped after a state failure")

            def uses_judge(self) -> bool:
                return True

        engine = _engine(_config(n_items=1))
        engine.state_adapter = _FailingEvaluateAdapter()
        engine.scorers = [*engine.scorers, _JudgeScorer()]
        result = engine.run()  # must not raise/assert from the judge scorer
        assert "quality" not in {s.name for s in result.items[0].scores}

    def test_snapshot_failure_under_fail_fast_still_fails_only_the_item(self):
        """Unlike StateResetError, this path is never fail_fast-gated either way
        -- it always fails the item, never the run."""
        engine = _engine(_config(n_items=1, extra_run={"fail_fast": True}))
        engine.state_adapter = _FailingEvaluateAdapter()
        result = engine.run()  # must not raise
        assert len(result.items) == 1


class TestNoLeakageAcrossRepeatedAttempts:
    def test_reset_runs_before_every_attempt_under_repetitions(self):
        adapter = _RecordingAdapter()
        engine = _engine(_config(n_items=1, extra_run={"repetitions": 4}))
        engine.state_adapter = adapter
        engine.run()
        assert adapter.calls.count("reset") == 4

    def test_reset_runs_before_every_attempt_under_repetitions_and_parallel(self):
        adapter = _ThreadSafeRecordingAdapter()
        engine = _engine(_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 2}))
        engine.state_adapter = adapter
        engine.run()
        assert adapter.calls.count("reset") == 6  # 2 items x 3 attempts


class TestConcurrencyLock:
    def test_state_lock_serializes_target_run_under_parallel_execution(self):
        """Decision C: a configured state_adapter serializes target.run() itself,
        not just the adapter's own calls -- the honest cost of a shared adapter
        under max_workers>1."""
        target = _InterleavingProbeTarget()
        adapter = _ThreadSafeRecordingAdapter()
        engine = _engine(_config(n_items=6, extra_run={"max_workers": 4}))
        engine.target = target
        engine.state_adapter = adapter
        engine.run()
        assert target.overlap_detected is False
        assert target.max_concurrent == 1

    def test_without_a_state_adapter_parallel_execution_is_unaffected(self):
        """Sanity control: the lock exists but is never touched absent an adapter,
        so ordinary parallel runs keep their normal concurrency."""
        target = _InterleavingProbeTarget()
        engine = _engine(_config(n_items=8, extra_run={"max_workers": 4}))
        engine.target = target
        engine.run()
        assert target.max_concurrent > 1  # real parallelism, unlike the locked case above


class TestConfigWiring:
    def test_state_adapter_config_field_constructs_a_real_registered_adapter(self):
        """End-to-end: EvalConfig.state_adapter -> STATE_ADAPTERS.create -> engine,
        using the real registered `in_memory` adapter, not a test double."""
        cfg = _config(n_items=1)
        cfg["state_adapter"] = {"type": "in_memory", "params": {"initial": {"k": 0}}}
        config = load_config_dict(cfg)
        engine = EvalEngine.from_config(config)
        engine.clock = _fixed_clock
        assert engine.state_adapter is not None
        result = engine.run()
        assert len(result.items) == 1

    def test_no_state_adapter_in_config_leaves_it_unset(self):
        config = load_config_dict(_config(n_items=1))
        engine = EvalEngine.from_config(config)
        assert engine.state_adapter is None
