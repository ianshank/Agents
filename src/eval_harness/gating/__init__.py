"""Quality gate: turns aggregate scores into a pass/fail CI decision.

All thresholds come from GateConfig; there are no baked-in cutoffs.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..config.models import EvalConfig, GateConfig
from ..core._execution_strategies import ITEM_ERROR_SCORE_NAME
from ..core.interfaces import Scorer, _uses_judge
from ..core.types import RunResult
from ..reliability import ReliabilityAggregator, ReliabilityReport

_RELIABILITY_METRICS = ("pass_at_k", "pass_power_k")


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


def _item_error_failures(gate: GateConfig, run: RunResult) -> list[str]:
    """Refuse to gate over a run whose sample was reduced by item failures.

    Under ``item_error_policy='record'`` an item whose target raised is kept as a
    visibly-failed result, but its scorers never ran — so it contributes to no
    scorer's aggregate. Every rule is then evaluated over the survivors, and a
    rule naming one of those scorers reads a healthy rate over a quietly smaller
    sample. That is the exact shape of the defect the record policy exists to
    surface, so the gate must not silently inherit it.

    Fabricating a per-scorer score for an item that produced none would be
    inventing data (``judges/panel.py`` excludes a failed member rather than
    counting it as a zero vote), so the gate reports the reduced sample instead
    and lets ``GateConfig.allow_item_errors`` decide.
    """
    if gate.allow_item_errors:
        return []
    failed = sum(1 for ir in run.items if any(s.name == ITEM_ERROR_SCORE_NAME for s in ir.scores))
    if not failed:
        return []
    return [
        f"{failed} of {len(run.items)} attempt(s) failed before scoring, so every rule below is "
        f"evaluated over a reduced sample (set gate.allow_item_errors=true to gate anyway)"
    ]


def evaluate_gate(gate: GateConfig | None, run: RunResult) -> GateResult:
    if gate is None or not gate.rules:
        return GateResult(passed=True)

    # Checked before any rule: a rule that reads a healthy rate over a reduced
    # sample is worse than no rule, because it looks like evidence.
    failures: list[str] = _item_error_failures(gate, run)

    # Computed at most once, lazily — only when a rule actually needs it, and
    # reused across every such rule in this gate rather than re-aggregated per rule.
    reliability_report: ReliabilityReport | None = None

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
