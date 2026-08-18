"""Quality gate: turns aggregate scores into a pass/fail CI decision.

All thresholds come from GateConfig; there are no baked-in cutoffs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config.models import GateConfig
from ..core.types import RunResult
from ..reliability import ReliabilityAggregator, ReliabilityReport

_RELIABILITY_METRICS = ("pass_at_k", "pass_power_k")


@dataclass
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def _reliability_rate(report: ReliabilityReport, score: str, metric: str) -> float | None:
    """Fraction of items whose per-item ``pass_at_k``/``pass_power_k`` boolean is
    True for *score*, or ``None`` when that scorer has no reliability data.

    Computed per item, never pooled across items (design.md's own requirement,
    already enforced by ``ReliabilityAggregator`` itself) — this only reduces
    each item's own boolean into a rate, it never re-derives pass/fail from
    pooled raw attempts.
    """
    entries = [e for e in report.per_item if e.scorer_name == score]
    if not entries:
        return None
    attr = "pass_at_k" if metric == "pass_at_k" else "pass_power_k"
    return sum(1 for e in entries if getattr(e, attr)) / len(entries)


def evaluate_gate(gate: GateConfig | None, run: RunResult) -> GateResult:
    if gate is None or not gate.rules:
        return GateResult(passed=True)

    # Computed at most once, lazily — only when a rule actually needs it, and
    # reused across every such rule in this gate rather than re-aggregated per rule.
    reliability_report: ReliabilityReport | None = None

    failures: list[str] = []
    for rule in gate.rules:
        if rule.metric in _RELIABILITY_METRICS:
            if reliability_report is None:
                reliability_report = ReliabilityAggregator.aggregate(run.items)
            observed = _reliability_rate(reliability_report, rule.score, rule.metric)
        else:
            agg = run.aggregate.get(rule.score)
            if agg is None:
                failures.append(f"score '{rule.score}' not present in results")
                continue
            observed = agg.mean if rule.metric == "mean" else agg.pass_rate
        if observed is None:
            failures.append(f"score '{rule.score}' has no {rule.metric}")
            continue
        if rule.min is not None and observed < rule.min:
            failures.append(f"{rule.score}.{rule.metric}={observed:.3f} below min {rule.min}")
        if rule.max is not None and observed > rule.max:
            failures.append(f"{rule.score}.{rule.metric}={observed:.3f} above max {rule.max}")
    return GateResult(passed=not failures, failures=failures)
