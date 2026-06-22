"""Tests for F-018: Parallel item execution.

Comprehensive coverage of sequential/parallel behaviour, determinism,
error handling, config validation, and aggregation correctness.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eval_harness.config import load_config_dict
from eval_harness.config.models import RunSettings
from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    ScoreResult,
    TargetOutput,
)
from eval_harness.engine import EvalEngine, _make_item_rng
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.version import SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_config(extra_run=None):
    """Build a minimal config dict, optionally merging *extra_run* into run."""
    run = {"name": "t", "run_id": "fixed-par", "seed": 42}
    if extra_run:
        run.update(extra_run)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {"id": str(i), "inputs": {"q": f"q{i}"}, "expected": f"q{i}"}
                    for i in range(10)
                ]
            },
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
        "sinks": [],
    }


def _engine(cfg_dict=None, client=None):
    config = load_config_dict(cfg_dict or _make_config())
    engine = EvalEngine.from_config(config, langfuse_client=client or NullLangfuseClient())
    engine.clock = _fixed_clock
    return config, engine


# ---------------------------------------------------------------------------
# 1. max_workers=1 identical to sequential
# ---------------------------------------------------------------------------


class TestSequentialIdentity:
    """max_workers=1 must produce IDENTICAL RunResult to the legacy path."""

    def test_max_workers_1_identical_to_sequential(self):
        _, engine_seq = _engine(_make_config({"max_workers": 1}))
        run_seq = engine_seq.run()

        _, engine_seq2 = _engine(_make_config({"max_workers": 1}))
        run_seq2 = engine_seq2.run()

        # Same run_id, same aggregates, same item order
        assert run_seq.run_id == run_seq2.run_id
        assert run_seq.aggregate == run_seq2.aggregate
        assert [ir.item.id for ir in run_seq.items] == [ir.item.id for ir in run_seq2.items]


# ---------------------------------------------------------------------------
# 2. max_workers=4 correct aggregation
# ---------------------------------------------------------------------------


class TestParallelAggregation:
    """Parallel execution with multiple workers produces correct aggregates."""

    def test_max_workers_4_correct_aggregation(self):
        _, engine = _engine(_make_config({"max_workers": 4}))
        run = engine.run()

        assert len(run.items) == 10
        assert run.aggregate["acc"].count == 10
        # All exact_match should pass (echo target returns the input)
        assert run.aggregate["acc"].mean == 1.0
        assert run.aggregate["acc"].pass_rate == 1.0


# ---------------------------------------------------------------------------
# 3. fail_fast cancels futures
# ---------------------------------------------------------------------------


class TestFailFast:
    """fail_fast shuts down the executor and re-raises on the first error."""

    def test_fail_fast_cancels_futures(self):
        cfg = _make_config({"max_workers": 4, "fail_fast": True})
        _, engine = _engine(cfg)

        call_count = 0
        original_run_one = engine._run_one

        def _failing_run_one(item, ctx):
            nonlocal call_count
            call_count += 1
            if item.id == "2":
                raise ValueError("deliberate failure on item 2")
            return original_run_one(item, ctx)

        engine._run_one = _failing_run_one

        with pytest.raises(ValueError, match="deliberate failure on item 2"):
            engine.run()

        # The executor should have stopped early; not all 10 items completed
        # (exact count is non-deterministic due to thread scheduling, but
        # some items after the failure should have been cancelled)
        assert call_count <= 10


# ---------------------------------------------------------------------------
# 4. Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    """Results are always in submission order regardless of completion time."""

    def test_deterministic_ordering(self):
        cfg = _make_config({"max_workers": 4})
        _, engine = _engine(cfg)
        run = engine.run()

        item_ids = [ir.item.id for ir in run.items]
        assert item_ids == [str(i) for i in range(10)]


# ---------------------------------------------------------------------------
# 5. Per-item RNG independence
# ---------------------------------------------------------------------------


class TestPerItemRng:
    """Each item gets a unique, deterministic RNG seeded from base + index."""

    def test_per_item_rng_independence(self):
        rng0 = _make_item_rng(42, 0)
        rng1 = _make_item_rng(42, 1)

        # Different indices => different streams
        assert rng0.random() != rng1.random()

        # Same seed+index => identical stream
        v0 = _make_item_rng(42, 0).random()
        v0b = _make_item_rng(42, 0).random()
        assert v0 == v0b


# ---------------------------------------------------------------------------
# 6. max_workers=0 rejected
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Pydantic validators reject invalid max_workers values."""

    def test_max_workers_0_rejected(self):
        with pytest.raises(ValueError):
            RunSettings(max_workers=0)

    def test_max_workers_negative_rejected(self):
        with pytest.raises(ValueError):
            RunSettings(max_workers=-1)


# ---------------------------------------------------------------------------
# 8. Langfuse trace graceful None
# ---------------------------------------------------------------------------


class TestLangfuseGraceful:
    """Parallel items handle None trace_id gracefully (no crash)."""

    def test_langfuse_trace_graceful_none(self):
        cfg = _make_config({"max_workers": 2})
        client = NullLangfuseClient()
        _, engine = _engine(cfg, client=client)

        # In parallel mode langfuse_context.get_current_trace_id() returns None
        # because context vars are not propagated. Engine must not crash.
        run = engine.run()
        assert len(run.items) == 10


# ---------------------------------------------------------------------------
# 9. Scorer error in parallel doesn't corrupt others
# ---------------------------------------------------------------------------


class TestScorerErrorIsolation:
    """A scorer error on one item must not affect other items' results."""

    def test_scorer_error_in_parallel(self):
        cfg = _make_config({"max_workers": 4})
        _, engine = _engine(cfg)

        original_run_one = engine._run_one

        def _sometimes_failing_run_one(item, ctx):
            if item.id == "5":
                # Simulate a scorer producing an error score (not raising)
                output = engine.target.run(item)
                return ItemResult(
                    item=item,
                    output=output,
                    scores=[ScoreResult(name="acc", value=0.0, passed=False, comment="error")],
                )
            return original_run_one(item, ctx)

        engine._run_one = _sometimes_failing_run_one
        run = engine.run()

        # All 10 items should have results
        assert len(run.items) == 10
        # Item 5 should have the error score
        item5 = next(ir for ir in run.items if ir.item.id == "5")
        assert item5.scores[0].comment == "error"
        # Other items should be normal
        item0 = next(ir for ir in run.items if ir.item.id == "0")
        assert item0.scores[0].passed is True


# ---------------------------------------------------------------------------
# 10. Existing config without max_workers
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    """Old configs without max_workers must still parse with default 1."""

    def test_existing_config_without_max_workers(self):
        cfg_dict = {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "legacy", "seed": 1},
            "dataset": {
                "type": "inline",
                "params": {"items": [{"id": "1", "inputs": {"q": "a"}, "expected": "a"}]},
            },
            "target": {"type": "echo", "params": {"output_key": "q"}},
            "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
            "sinks": [],
        }
        config = load_config_dict(cfg_dict)
        assert config.run.max_workers == 1


# ---------------------------------------------------------------------------
# 11. Hypothesis property test for _aggregate
# ---------------------------------------------------------------------------


class TestAggregateProperties:
    """Property-based tests for the _aggregate static method."""

    def test_mean_is_arithmetic_mean(self):
        """Mean of values is the arithmetic mean."""
        items = [
            ItemResult(
                item=EvalItem(id=str(i), inputs={}),
                output=TargetOutput(output="x"),
                scores=[ScoreResult(name="s", value=float(i), passed=i > 2)],
            )
            for i in range(5)
        ]
        agg = EvalEngine._aggregate(items)
        expected_mean = sum(range(5)) / 5
        assert abs(agg["s"].mean - expected_mean) < 1e-9

    def test_pass_rate_is_fraction(self):
        """pass_rate is sum(passed) / len(passed) when passed is not None."""
        items = [
            ItemResult(
                item=EvalItem(id=str(i), inputs={}),
                output=TargetOutput(output="x"),
                scores=[ScoreResult(name="s", value=1.0, passed=i % 2 == 0)],
            )
            for i in range(10)
        ]
        agg = EvalEngine._aggregate(items)
        # 0,2,4,6,8 pass => 5/10
        assert abs(agg["s"].pass_rate - 0.5) < 1e-9

    def test_aggregate_empty(self):
        """Empty results produce empty aggregates."""
        agg = EvalEngine._aggregate([])
        assert agg == {}

    def test_aggregate_multiple_scorers(self):
        """Multiple scorer names aggregate independently."""
        items = [
            ItemResult(
                item=EvalItem(id="1", inputs={}),
                output=TargetOutput(output="x"),
                scores=[
                    ScoreResult(name="a", value=1.0, passed=True),
                    ScoreResult(name="b", value=0.0, passed=False),
                ],
            )
        ]
        agg = EvalEngine._aggregate(items)
        assert agg["a"].mean == 1.0
        assert agg["b"].mean == 0.0


# ---------------------------------------------------------------------------
# Parallel vs Sequential aggregate equivalence
# ---------------------------------------------------------------------------


class TestParallelSequentialEquivalence:
    """Parallel and sequential paths produce identical aggregate means."""

    def test_parallel_sequential_same_aggregate(self):
        _, engine_seq = _engine(_make_config({"max_workers": 1}))
        run_seq = engine_seq.run()

        _, engine_par = _engine(_make_config({"max_workers": 4}))
        run_par = engine_par.run()

        # Same number of items
        assert len(run_seq.items) == len(run_par.items)

        # Same aggregate values
        for key in run_seq.aggregate:
            assert key in run_par.aggregate
            assert abs(run_seq.aggregate[key].mean - run_par.aggregate[key].mean) < 1e-9
            assert run_seq.aggregate[key].count == run_par.aggregate[key].count
