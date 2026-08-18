"""Quality gate: turns aggregate scores into a pass/fail CI decision.

All thresholds come from GateConfig; there are no baked-in cutoffs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..config.models import EvalConfig, GateConfig
from ..core.interfaces import Scorer
from ..core.types import RunResult
from ..reliability import ReliabilityAggregator, ReliabilityReport

_RELIABILITY_METRICS = ("pass_at_k", "pass_power_k")


def _uses_judge(scorer: Scorer) -> bool:
    """Whether *scorer* is judge-backed; tolerates one predating ``Scorer.uses_judge``."""
    method = getattr(scorer, "uses_judge", None)
    return bool(method()) if callable(method) else False


def require_calibration_for_judge_gating(config: EvalConfig, scorers: Iterable[Scorer]) -> None:
    """Raise if a gate rule targets a judge-backed scorer with no named calibration.

    ``spec.md`` "Gating requires a named calibration artifact": a config that marks
    a judge as gating — one of ``config.gate.rules`` names a scorer whose real,
    resolved ``uses_judge()`` is true — without a ``judge_calibration`` block is
    rejected. Checked against the *actual constructed* ``scorers`` (each one's real
    ``.name``/``.uses_judge()``), not guessed from raw config, so a scorer's own
    name-resolution/default-name logic never needs duplicating here. Call once the
    engine's scorers are built (``EvalEngine.from_config``), before ``evaluate_gate``.
    """
    if config.gate is None or not config.gate.rules:
        return
    judge_backed_names = {s.name for s in scorers if _uses_judge(s)}
    gated_names = {rule.score for rule in config.gate.rules}
    targeted = judge_backed_names & gated_names
    if targeted and config.judge_calibration is None:
        raise ValueError(
            f"judge_calibration.calibration_artifact_id is required to gate on "
            f"{sorted(targeted)!r}: a judge's participation in gating must be traceable "
            "to the calibration run that authorised it"
        )


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
