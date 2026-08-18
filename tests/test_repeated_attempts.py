"""Tests for repeated-attempt execution (F-056 reliability metrics, Group 3).

Covers the attempt loop, per-attempt RNG reset, ``is_deterministic`` detection,
and the ``deterministic_sampling`` diagnostic — both the sequential
(``max_workers=1``) and parallel dispatch paths. ``repetitions=1`` (the default)
is covered separately by ``tests/test_engine.py`` /
``tests/test_parallel_execution.py``, which this change leaves untouched.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from eval_harness.config import load_config_dict
from eval_harness.core.interfaces import Scorer, TargetRunner
from eval_harness.core.types import EvalItem, ScoreResult, TargetOutput
from eval_harness.engine import EvalEngine, _make_item_rng
from eval_harness.plugins import SCORERS, TARGETS
from eval_harness.version import SCHEMA_VERSION


def _fixed_clock():
    return datetime(2026, 1, 1, tzinfo=UTC)


def _make_config(n_items=4, extra_run=None, scorer_type="exact_match"):
    run = {"name": "t", "run_id": "fixed-rep", "seed": 42}
    if extra_run:
        run.update(extra_run)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": run,
        "dataset": {
            "type": "inline",
            "params": {
                "items": [{"id": str(i), "inputs": {"q": f"q{i}"}, "expected": f"q{i}"} for i in range(n_items)]
            },
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": scorer_type, "params": {"name": "acc"}}],
        "sinks": [],
    }


def _engine(cfg):
    config = load_config_dict(cfg)
    engine = EvalEngine.from_config(config)
    engine.clock = _fixed_clock
    return engine


class _CountingTarget(TargetRunner):
    """Records every ``item.inputs`` it was called with, in call order."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, item: EvalItem) -> TargetOutput:
        self.calls.append(dict(item.inputs))
        return TargetOutput(output=f"out-{item.id}-{len(self.calls)}")


class _RngProbeScorer(Scorer):
    """Draws from ``ctx.rng`` and derives ``passed`` from the draw — exposes
    whether the scorer RNG is reset (stable draw/verdict per item across
    attempts) or merely shared-and-advancing (drifting draw per attempt)."""

    default_name = "rng_probe"

    def score(self, item, output, ctx):
        draw = ctx.rng.random()
        return ScoreResult(self.name, value=draw, passed=draw < 0.5)


class _AlwaysPassScorer(Scorer):
    """Ignores target output entirely, so a diagnostic test can isolate the
    determinism condition from scoring correctness."""

    default_name = "always_pass"

    def score(self, item, output, ctx):
        return ScoreResult(self.name, value=1.0, passed=True)


class _VaryingTarget(TargetRunner):
    """A different output every call — ``is_deterministic()`` undeclared
    (``None``), forcing the engine's observed-output fallback to see genuine
    variance."""

    def __init__(self) -> None:
        self.n = 0

    def run(self, item: EvalItem) -> TargetOutput:
        self.n += 1
        return TargetOutput(output=f"v{self.n}")


class _AbstainsOnceScorer(Scorer):
    """Abstains (``passed=None``) on an item's first-seen attempt, passes on
    every attempt after — proving an inconclusive verdict is excluded from the
    pass^k diagnostic check rather than silently coerced to a pass or fail."""

    default_name = "abstains_once"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self._seen: set[str] = set()

    def score(self, item, output, ctx):
        first_time = item.id not in self._seen
        self._seen.add(item.id)
        return ScoreResult(self.name, value=1.0, passed=None if first_time else True)


class _DeclaredDeterministicTarget(TargetRunner):
    """Declares determinism explicitly, so the engine trusts it directly rather
    than falling back to observing attempt outputs (declared/derived takes
    priority over observed — design.md's detection priority order)."""

    def run(self, item: EvalItem) -> TargetOutput:
        return TargetOutput(output=item.inputs["q"])

    def is_deterministic(self) -> bool | None:
        return True


class TestAttemptCount:
    def test_repetitions_five_invokes_target_exactly_five_times_per_item(self):
        TARGETS.register_class("counting", _CountingTarget)
        try:
            cfg = _make_config(n_items=3, extra_run={"repetitions": 5, "max_workers": 1})
            cfg["target"] = {"type": "counting", "params": {}}
            engine = _engine(cfg)
            run = engine.run()
            assert len(engine.target.calls) == 15  # 3 items x 5 attempts, no memoisation
            assert len(run.items) == 15
        finally:
            TARGETS._reg.pop("counting", None)

    def test_repetitions_five_parallel_invokes_target_exactly_five_times_per_item(self):
        TARGETS.register_class("counting", _CountingTarget)
        try:
            cfg = _make_config(n_items=3, extra_run={"repetitions": 5, "max_workers": 4})
            cfg["target"] = {"type": "counting", "params": {}}
            engine = _engine(cfg)
            run = engine.run()
            assert len(engine.target.calls) == 15
            assert len(run.items) == 15
        finally:
            TARGETS._reg.pop("counting", None)

    def test_every_attempt_receives_byte_identical_input(self):
        """The harness introduces no variance of its own — every attempt of an
        item is called with the identical inputs dict."""
        TARGETS.register_class("counting", _CountingTarget)
        try:
            cfg = _make_config(n_items=2, extra_run={"repetitions": 4, "max_workers": 1})
            cfg["target"] = {"type": "counting", "params": {}}
            engine = _engine(cfg)
            engine.run()
            # 2 items x 4 attempts; every call for a given q-value is identical.
            by_q = defaultdict(list)
            for call in engine.target.calls:
                by_q[call["q"]].append(call)
            assert len(by_q) == 2
            for _q, calls in by_q.items():
                assert len(calls) == 4
                assert all(c == calls[0] for c in calls)
        finally:
            TARGETS._reg.pop("counting", None)


class TestDuplicateIdCheck:
    def test_no_duplicate_id_warning_for_attempts_of_the_same_item(self, caplog):
        cfg = _make_config(n_items=3, extra_run={"repetitions": 5, "max_workers": 1})
        engine = _engine(cfg)
        with caplog.at_level(logging.WARNING, logger="eval_harness.engine"):
            engine.run()
        assert "Duplicate item ID" not in caplog.text


class TestPerAttemptRngReset:
    def test_sequential_stable_verdict_across_attempts(self):
        """A deterministic target (echo) scored by a scorer that draws from
        ctx.rng must not manufacture cross-attempt flakiness: the RNG resets to
        the item's seed at the start of every attempt."""
        SCORERS.register_class("rng_probe", _RngProbeScorer)
        try:
            cfg = _make_config(n_items=4, extra_run={"repetitions": 5, "max_workers": 1}, scorer_type="rng_probe")
            engine = _engine(cfg)
            run = engine.run()
            by_item = defaultdict(list)
            for ir in run.items:
                by_item[ir.item.id].append(ir.scores[0])
            assert len(by_item) == 4
            for item_id, scores in by_item.items():
                assert len(scores) == 5
                draws = {s.value for s in scores}
                assert len(draws) == 1, f"item {item_id}: RNG drew different values across attempts: {draws}"
                verdicts = {s.passed for s in scores}
                assert len(verdicts) == 1, f"item {item_id}: verdict flip-flopped across attempts: {verdicts}"
        finally:
            SCORERS._reg.pop("rng_probe", None)

    def test_parallel_stable_verdict_across_attempts(self):
        SCORERS.register_class("rng_probe", _RngProbeScorer)
        try:
            cfg = _make_config(n_items=4, extra_run={"repetitions": 5, "max_workers": 4}, scorer_type="rng_probe")
            engine = _engine(cfg)
            run = engine.run()
            by_item = defaultdict(list)
            for ir in run.items:
                by_item[ir.item.id].append(ir.scores[0])
            for item_id, scores in by_item.items():
                assert len({s.value for s in scores}) == 1, item_id
        finally:
            SCORERS._reg.pop("rng_probe", None)

    def test_sequential_repeated_attempts_get_distinct_per_item_seeds(self):
        """The trap: RunContext.item_index defaults to 0 and the single-attempt
        sequential path never sets it. If repetitions>1 code sourced its
        per-attempt seed from ctx.item_index instead of this loop's own
        enumerate() index, every item's attempts would collide on base_seed+0."""
        SCORERS.register_class("rng_probe", _RngProbeScorer)
        try:
            cfg = _make_config(
                n_items=5, extra_run={"repetitions": 3, "seed": 7, "max_workers": 1}, scorer_type="rng_probe"
            )
            engine = _engine(cfg)
            run = engine.run()
            first_draw_by_item = {ir.item.id: ir.scores[0].value for ir in run.items if ir.attempt_index == 0}
            expected = {str(idx): _make_item_rng(7, idx).random() for idx in range(5)}
            assert first_draw_by_item == expected
        finally:
            SCORERS._reg.pop("rng_probe", None)


class TestReliabilityDiagnostics:
    def test_absent_at_repetitions_one(self):
        cfg = _make_config(n_items=2)
        engine = _engine(cfg)
        run = engine.run()
        assert run.diagnostics == []
        assert "reliability" not in run.to_dict()

    def test_present_for_deterministic_target_with_perfect_pass_power_k(self):
        SCORERS.register_class("always_pass", _AlwaysPassScorer)
        try:
            cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 1}, scorer_type="always_pass")
            engine = _engine(cfg)
            run = engine.run()
            assert len(run.diagnostics) == 1
            assert run.diagnostics[0]["code"] == "deterministic_sampling"
            assert run.to_dict()["reliability"]["diagnostics"] == run.diagnostics
        finally:
            SCORERS._reg.pop("always_pass", None)

    def test_present_via_declared_determinism_without_observing_outputs(self):
        """The declared/derived tier is trusted directly — the engine does not
        need to fall back to comparing attempt outputs when the target states
        its own determinism."""
        SCORERS.register_class("always_pass", _AlwaysPassScorer)
        TARGETS.register_class("declared_deterministic", _DeclaredDeterministicTarget)
        try:
            cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 1}, scorer_type="always_pass")
            cfg["target"] = {"type": "declared_deterministic", "params": {}}
            engine = _engine(cfg)
            run = engine.run()
            assert len(run.diagnostics) == 1
            assert run.diagnostics[0]["code"] == "deterministic_sampling"
        finally:
            SCORERS._reg.pop("always_pass", None)
            TARGETS._reg.pop("declared_deterministic", None)

    def test_absent_when_a_scorer_abstains_on_one_attempt(self):
        """An inconclusive (None) verdict on even one attempt means pass^k isn't
        cleanly 1.0 — the diagnostic must not fire from a partial signal."""
        SCORERS.register_class("abstains_once", _AbstainsOnceScorer)
        try:
            cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 1}, scorer_type="abstains_once")
            engine = _engine(cfg)
            run = engine.run()
            assert run.diagnostics == []
        finally:
            SCORERS._reg.pop("abstains_once", None)

    def test_absent_for_nondeterministic_target_that_passes_all_k(self):
        """That agent was genuinely measured — no vacuous-pass caveat applies."""
        SCORERS.register_class("always_pass", _AlwaysPassScorer)
        TARGETS.register_class("varying", _VaryingTarget)
        try:
            cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 1}, scorer_type="always_pass")
            cfg["target"] = {"type": "varying", "params": {}}
            engine = _engine(cfg)
            run = engine.run()
            assert run.diagnostics == []
        finally:
            SCORERS._reg.pop("always_pass", None)
            TARGETS._reg.pop("varying", None)


class TestAttemptIdentityThroughTheEngine:
    def test_sequential_attempt_fields_populated(self):
        cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 1})
        engine = _engine(cfg)
        run = engine.run()
        assert len(run.items) == 6
        for ir in run.items:
            assert ir.attempt_index in (0, 1, 2)
            assert ir.attempt_id == f"{ir.item.id}:{ir.attempt_index}"
            assert ir.item_run_id == f"fixed-rep:{ir.item.id}"

    def test_parallel_attempt_fields_populated(self):
        cfg = _make_config(n_items=2, extra_run={"repetitions": 3, "max_workers": 4})
        engine = _engine(cfg)
        run = engine.run()
        assert len(run.items) == 6
        for ir in run.items:
            assert ir.attempt_index in (0, 1, 2)
            assert ir.attempt_id == f"{ir.item.id}:{ir.attempt_index}"
            assert ir.item_run_id == f"fixed-rep:{ir.item.id}"

    def test_attempts_of_the_same_item_are_grouped_and_ordered(self):
        """Item-major, attempts ascending within an item — both dispatch paths."""
        for max_workers in (1, 4):
            cfg = _make_config(n_items=3, extra_run={"repetitions": 4, "max_workers": max_workers})
            engine = _engine(cfg)
            run = engine.run()
            by_item_order = defaultdict(list)
            for ir in run.items:
                by_item_order[ir.item.id].append(ir.attempt_index)
            for item_id, order in by_item_order.items():
                assert order == [0, 1, 2, 3], (max_workers, item_id, order)
