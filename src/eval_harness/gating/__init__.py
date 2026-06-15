"""Quality gate: turns aggregate scores into a pass/fail CI decision.

All thresholds come from GateConfig; there are no baked-in cutoffs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config.models import GateConfig
from ..core.types import RunResult


@dataclass
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def evaluate_gate(gate: GateConfig | None, run: RunResult) -> GateResult:
    if gate is None or not gate.rules:
        return GateResult(passed=True)

    failures: list[str] = []
    for rule in gate.rules:
        agg = run.aggregate.get(rule.score)
        if agg is None:
            failures.append(f"score '{rule.score}' not present in results")
            continue
        observed = agg.mean if rule.metric == "mean" else agg.pass_rate
        if observed is None:
            failures.append(f"score '{rule.score}' has no {rule.metric}")
            continue
        if rule.min is not None and observed < rule.min:
            failures.append(
                f"{rule.score}.{rule.metric}={observed:.3f} below min {rule.min}"
            )
        if rule.max is not None and observed > rule.max:
            failures.append(
                f"{rule.score}.{rule.metric}={observed:.3f} above max {rule.max}"
            )
    return GateResult(passed=not failures, failures=failures)
