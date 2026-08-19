"""Tests for ReliabilityAggregator (F-056 reliability metrics, Group 4).

Pure, standalone tests — no engine, no config, no I/O. Every fixture is built
directly from eval_harness.core.types.
"""

from __future__ import annotations

from eval_harness.core.types import EvalItem, ItemResult, ScoreResult, TargetOutput
from eval_harness.reliability import ReliabilityAggregator, ReliabilityReport


def _item(item_id: str) -> EvalItem:
    return EvalItem(id=item_id, inputs={})


def _attempt(
    item_id: str,
    attempt_index: int,
    *,
    passed: bool | None,
    value: float = 1.0,
    latency_ms: float | None = None,
    error: str | None = None,
    cost: float | None = None,
    scorer_name: str = "acc",
) -> ItemResult:
    metadata = {} if cost is None else {"cost": cost}
    output = TargetOutput(output="x", latency_ms=latency_ms, error=error, metadata=metadata)
    return ItemResult(
        item=_item(item_id),
        output=output,
        scores=[ScoreResult(name=scorer_name, value=value, passed=passed)],
        attempt_index=attempt_index,
        attempt_id=f"{item_id}:{attempt_index}",
        item_run_id=f"run:{item_id}",
    )


def _entry(report: ReliabilityReport, item_id: str, scorer_name: str = "acc"):
    matches = [ir for ir in report.per_item if ir.item_id == item_id and ir.scorer_name == scorer_name]
    assert len(matches) == 1, f"expected exactly one entry for ({item_id}, {scorer_name}), got {len(matches)}"
    return matches[0]


class TestBasicCounts:
    def test_all_pass(self):
        items = [_attempt("i1", a, passed=True) for a in range(5)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.attempts == 5
        assert entry.success_count == 5
        assert entry.pass_rate == 1.0
        assert entry.pass_at_k is True
        assert entry.pass_power_k is True

    def test_all_fail(self):
        items = [_attempt("i1", a, passed=False) for a in range(5)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.success_count == 0
        assert entry.pass_rate == 0.0
        assert entry.pass_at_k is False
        assert entry.pass_power_k is False

    def test_one_of_five_passes_pass_at_k_true_pass_power_k_false(self):
        items = [_attempt("i1", a, passed=(a == 2)) for a in range(5)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.success_count == 1
        assert entry.pass_rate == 0.2
        assert entry.pass_at_k is True
        assert entry.pass_power_k is False

    def test_abstained_attempt_excluded_from_pass_power_k(self):
        """An inconclusive (None) verdict on even one attempt means pass^k can't
        be cleanly True — the aggregator must not silently coerce it."""
        items = [_attempt("i1", 0, passed=None), *[_attempt("i1", a, passed=True) for a in range(1, 5)]]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.attempts == 5
        assert entry.success_count == 4
        assert entry.pass_power_k is False  # 4 known-passing != 5 attempts
        assert entry.pass_at_k is True  # at least one confirmed pass exists


class TestNeverPooledAcrossItems:
    def test_pass_power_k_is_per_item_not_pooled(self):
        """design.md: pooling across items would let easy items mask a task that
        fails half the time. 9 easy items (all-pass) + 1 unreliable item
        (1-of-5) must not average out to a falsely-high pooled signal — each
        item keeps its own independent pass^k."""
        items = []
        for i in range(9):
            items += [_attempt(f"easy{i}", a, passed=True) for a in range(5)]
        items += [_attempt("hard", a, passed=(a == 0)) for a in range(5)]

        report = ReliabilityAggregator.aggregate(items)
        assert len(report.per_item) == 10
        for i in range(9):
            assert _entry(report, f"easy{i}").pass_power_k is True
        hard_entry = _entry(report, "hard")
        assert hard_entry.pass_power_k is False
        assert hard_entry.pass_rate == 0.2
        # No run-wide/pooled field exists on ItemReliability or ReliabilityReport —
        # only per-item entries, so there is nothing to average this signal away into.


class TestDistributions:
    def test_score_quantiles_cover_all_attempts_including_failures(self):
        items = [_attempt("i1", a, passed=(a % 2 == 0), value=float(a)) for a in range(5)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert set(entry.score_quantiles) == {"p50", "p90", "p99"}
        assert entry.score_quantiles["p50"] == 2.0  # median of [0,1,2,3,4]

    def test_latency_and_cost_scoped_to_successful_attempts_only(self):
        """Cost and latency are per *successful* attempt, not per raw run — a
        failed attempt's latency/cost must not pollute either distribution."""
        items = [
            _attempt("i1", 0, passed=True, latency_ms=100.0, cost=1.0),
            _attempt("i1", 1, passed=True, latency_ms=200.0, cost=2.0),
            _attempt("i1", 2, passed=False, latency_ms=9999.0, cost=9999.0),
        ]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.latency_quantiles["p50"] == 150.0  # median of [100, 200] only — 9999 excluded
        assert max(entry.latency_quantiles.values()) < 9999.0
        assert entry.cost_per_success == 1.5

    def test_cost_per_success_none_when_no_target_populates_it(self):
        """No target in this repo populates metadata['cost'] today — the
        aggregator must report that honestly (None), never a fabricated 0."""
        items = [_attempt("i1", a, passed=True) for a in range(3)]
        report = ReliabilityAggregator.aggregate(items)
        assert _entry(report, "i1").cost_per_success is None

    def test_failure_categories_distinguish_target_error_scorer_fail_inconclusive(self):
        items = [
            _attempt("i1", 0, passed=False, error="boom"),
            _attempt("i1", 1, passed=False),
            _attempt("i1", 2, passed=None),
            _attempt("i1", 3, passed=True),
        ]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.failure_categories == {"target_error": 1, "scorer_fail": 1, "inconclusive": 1}

    def test_single_successful_attempt_quantiles_equal_that_value(self):
        """statistics.quantiles requires >=2 points; a single value's p50/p90/p99
        are trivially that value — not an error, not an empty dict."""
        items = [_attempt("i1", 0, passed=True, latency_ms=42.0)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.latency_quantiles == {"p50": 42.0, "p90": 42.0, "p99": 42.0}

    def test_empty_distributions_when_no_data(self):
        """A quantile dict is empty, never a fabricated zero, when there is
        nothing to summarise (e.g. every attempt failed, so no successful
        latency/cost values exist)."""
        items = [_attempt("i1", a, passed=False) for a in range(3)]
        report = ReliabilityAggregator.aggregate(items)
        entry = _entry(report, "i1")
        assert entry.latency_quantiles == {}
        assert entry.cost_per_success is None


class TestMultiScorer:
    def test_scorers_aggregated_independently_per_item(self):
        items = []
        for a in range(5):
            output = TargetOutput(output="x")
            items.append(
                ItemResult(
                    item=_item("i1"),
                    output=output,
                    scores=[
                        ScoreResult(name="acc", value=1.0, passed=True),
                        ScoreResult(name="quality", value=0.5, passed=(a < 2)),
                    ],
                    attempt_index=a,
                    attempt_id=f"i1:{a}",
                    item_run_id="run:i1",
                )
            )
        report = ReliabilityAggregator.aggregate(items)
        assert len(report.per_item) == 2
        acc = _entry(report, "i1", "acc")
        quality = _entry(report, "i1", "quality")
        assert acc.pass_power_k is True
        assert quality.pass_power_k is False
        assert quality.success_count == 2

    def test_item_attempts_reflects_the_true_count_even_when_a_scorer_is_conditionally_absent(self):
        """F-057's engine.py skips a judge-backed scorer on any attempt where a
        programmatic scorer already failed, so a judge's own `attempts` (how many
        ScoreResults it actually produced) can be lower than the item's true
        repetition count. `item_attempts` must still report the true count for
        every scorer -- including the one that was conditionally absent -- so a
        reader isn't misled into treating a partial-participation scorer's
        `attempts` as the number of repetitions the item received."""
        # 5 attempts total; "judge" only ran (and always passed) on the 2 where "acc" passed.
        acc_passed = [True, False, True, False, False]
        items = [
            ItemResult(
                item=_item("i1"),
                output=TargetOutput(output="x"),
                scores=(
                    [ScoreResult(name="acc", value=1.0, passed=passed)]
                    + ([ScoreResult(name="judge", value=1.0, passed=True)] if passed else [])
                ),
                attempt_index=a,
                attempt_id=f"i1:{a}",
                item_run_id="run:i1",
            )
            for a, passed in enumerate(acc_passed)
        ]
        report = ReliabilityAggregator.aggregate(items)

        acc = _entry(report, "i1", "acc")
        assert acc.attempts == 5
        assert acc.item_attempts == 5

        judge = _entry(report, "i1", "judge")
        assert judge.attempts == 2  # only recorded twice
        assert judge.item_attempts == 5  # but the item was truly attempted 5 times
        assert judge.pass_rate == 1.0  # 2/2 among the attempts it did run


class TestPurity:
    def test_calling_twice_yields_identical_results(self):
        """No I/O, clock or RNG — same input always produces the same output."""
        items = [_attempt("i1", a, passed=(a % 2 == 0), value=float(a), latency_ms=float(a * 10)) for a in range(5)]
        r1 = ReliabilityAggregator.aggregate(items)
        r2 = ReliabilityAggregator.aggregate(items)
        assert r1 == r2

    def test_empty_input_yields_empty_report(self):
        report = ReliabilityAggregator.aggregate([])
        assert report.per_item == ()
