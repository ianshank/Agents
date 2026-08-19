"""Pure aggregation of repeated-attempt results into per-item reliability metrics.

No I/O, clock or RNG — a function over persisted :class:`~eval_harness.core.types.ItemResult`
records (``add-repeat-reliability-metrics``, ``design.md`` "Aggregation"). Callers select which
records to pass in (typically a ``repetitions > 1`` run's ``RunResult.items``) and are responsible
for reducing the resulting per-item booleans into a run-level gate metric — see
``eval_harness.gating``. ``pass^k`` is computed **per item** here and never pooled across items:
pooling raw attempt counts across a suite would let easy items mask a task that fails half the
time, exactly the signal this metric exists to surface (``design.md``).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .core.types import ItemResult, ScoreResult

_QUANTILE_POINTS = {"p50": 49, "p90": 89, "p99": 98}


@dataclass(frozen=True)
class ItemReliability:
    """Reliability of one (item, scorer) pair across its recorded attempts.

    ``attempts`` and ``item_attempts`` can diverge: a judge-backed scorer may be
    conditionally skipped on some of an item's attempts (F-057's judge-after-
    programmatic-failure skip records no ``ScoreResult`` at all for that attempt),
    so ``attempts`` (this scorer's own recorded count) can be lower than
    ``item_attempts`` (the item's true repetition count, shared by every scorer).
    Reading ``attempts`` alone as "how many times this item was run" is the trap;
    both fields together make a partial-participation scorer's coverage visible.
    """

    item_id: str
    scorer_name: str
    attempts: int
    item_attempts: int
    success_count: int
    pass_rate: float
    pass_at_k: bool
    pass_power_k: bool
    score_quantiles: dict[str, float]
    latency_quantiles: dict[str, float]
    cost_per_success: float | None
    failure_categories: dict[str, int]


@dataclass(frozen=True)
class ReliabilityReport:
    per_item: tuple[ItemReliability, ...]


def _quantiles(values: list[float]) -> dict[str, float]:
    """p50/p90/p99 of *values*, or ``{}`` when there is nothing to summarise.

    A single value's p50/p90/p99 are all that one value — mathematically correct,
    not a special case worth flagging to a caller.
    """
    if not values:
        return {}
    if len(values) == 1:
        return dict.fromkeys(_QUANTILE_POINTS, values[0])
    cuts = statistics.quantiles(values, n=100)
    return {label: cuts[idx] for label, idx in _QUANTILE_POINTS.items()}


def _failure_category(ir: ItemResult, passed: bool | None) -> str:
    """Classify one non-passing attempt from data that already exists —
    no invented taxonomy beyond what ``TargetOutput``/``ScoreResult`` record."""
    if ir.output.error is not None:
        return "target_error"
    if passed is None:
        return "inconclusive"
    return "scorer_fail"


class ReliabilityAggregator:
    """Aggregates raw attempt records into per-(item, scorer) reliability stats."""

    @staticmethod
    def aggregate(items: list[ItemResult]) -> ReliabilityReport:
        by_item: dict[str, list[ItemResult]] = {}
        for ir in items:
            by_item.setdefault(ir.item.id, []).append(ir)

        per_item: list[ItemReliability] = []
        for item_id, item_results in by_item.items():
            by_scorer: dict[str, list[tuple[ItemResult, ScoreResult]]] = {}
            for ir in item_results:
                for s in ir.scores:
                    by_scorer.setdefault(s.name, []).append((ir, s))

            for scorer_name, pairs in by_scorer.items():
                per_item.append(_aggregate_one(item_id, scorer_name, pairs, item_attempts=len(item_results)))

        return ReliabilityReport(per_item=tuple(per_item))


def _aggregate_one(
    item_id: str,
    scorer_name: str,
    pairs: list[tuple[ItemResult, ScoreResult]],
    *,
    item_attempts: int,
) -> ItemReliability:
    attempts = len(pairs)
    known = [(ir, s) for ir, s in pairs if s.passed is not None]
    success = [(ir, s) for ir, s in known if s.passed]

    success_count = len(success)
    pass_rate = success_count / attempts if attempts else 0.0
    pass_at_k = any(s.passed for _, s in known)
    pass_power_k = len(known) == attempts and all(s.passed for _, s in known)

    score_quantiles = _quantiles([s.value for _, s in pairs])
    latency_values = [ir.output.latency_ms for ir, _ in success if ir.output.latency_ms is not None]
    latency_quantiles = _quantiles(latency_values)

    raw_costs = (ir.output.metadata.get("cost") for ir, _ in success)
    costs = [c for c in raw_costs if isinstance(c, (int, float))]
    cost_per_success = statistics.fmean(costs) if costs else None

    failure_categories: dict[str, int] = {}
    for ir, s in pairs:
        if not s.passed:
            category = _failure_category(ir, s.passed)
            failure_categories[category] = failure_categories.get(category, 0) + 1

    return ItemReliability(
        item_id=item_id,
        scorer_name=scorer_name,
        attempts=attempts,
        item_attempts=item_attempts,
        success_count=success_count,
        pass_rate=pass_rate,
        pass_at_k=pass_at_k,
        pass_power_k=pass_power_k,
        score_quantiles=score_quantiles,
        latency_quantiles=latency_quantiles,
        cost_per_success=cost_per_success,
        failure_categories=failure_categories,
    )
