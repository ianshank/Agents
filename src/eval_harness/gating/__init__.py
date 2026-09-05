"""Quality gate: turns aggregate scores into a pass/fail CI decision.

All thresholds come from GateConfig; there are no baked-in cutoffs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..config.models import EvalConfig, GateConfig, GateRule
from ..core._execution_strategies import ITEM_ERROR_SCORE_NAME
from ..core.interfaces import Scorer, _uses_judge
from ..core.types import GateDecision, GateRuleRecord, RunResult
from ..reliability import ReliabilityAggregator, ReliabilityReport

logger = logging.getLogger(__name__)

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
    # Only a rule that can actually block counts as "gating". An advisory rule
    # is measuring the judge, not trusting it -- and demanding a calibration
    # artifact before a judge may be *measured* makes calibration unreachable,
    # because the labelled corpus that produces the artifact is assembled from
    # exactly these advisory runs. The fail-closed refusal below stays exactly
    # as strict for every rule that can block.
    gated_names = {rule.score for rule in config.gate.rules if not rule.report_only}
    targeted = judge_backed_names & gated_names
    if targeted and config.judge_calibration is None:
        raise ValueError(
            f"judge_calibration.calibration_artifact_id is required to gate on "
            f"{sorted(targeted)!r}: a judge's participation in gating must be traceable "
            "to the calibration run that authorised it"
        )


@dataclass
class GateResult:
    """The gate's verdict.

    ``failures`` holds only *blocking* reasons, so its existing meaning —
    "non-empty implies the run is blocked" — is unchanged, and every existing
    caller that reads ``passed``/``failures`` keeps working.

    ``advisory`` and ``rules`` are appended last with defaults, the additive
    shape ``RunResult.diagnostics`` and ``ItemResult.attempt_index`` already
    established (ADR 0031 obligation 1).
    """

    passed: bool
    failures: list[str] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)
    rules: list[GateRuleRecord] = field(default_factory=list)

    def to_decision(self) -> GateDecision:
        """Render as the plain record the engine attaches to ``RunResult``.

        ``GateDecision`` lives in ``core`` so that ``RunResult`` can name it
        without ``core`` importing ``gating``; this method is the one place the
        two shapes are mapped onto each other.
        """
        return GateDecision(
            passed=self.passed,
            blocking_failures=list(self.failures),
            advisory_failures=list(self.advisory),
            rules=list(self.rules),
        )


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


def _record(rule: GateRule, observed: float | None, unmet: list[str]) -> GateRuleRecord:
    """Build one rule's outcome record.

    ``unmet`` is the (possibly empty) list of reasons this rule was not
    satisfied; a rule is met exactly when that list is empty. Keeping the
    met/unmet decision here — derived from the reasons rather than asserted
    alongside them — is what stops a record claiming ``met=True`` while
    carrying a failure string.
    """
    detail = "; ".join(unmet) if unmet else f"{rule.score}.{rule.metric} within bounds"
    return GateRuleRecord(
        score=rule.score,
        metric=rule.metric,
        observed=observed,
        minimum=rule.min,
        maximum=rule.max,
        met=not unmet,
        advisory=rule.report_only,
        detail=detail,
    )


def _evaluate_rule(
    rule: GateRule,
    run: RunResult,
    reliability_report: ReliabilityReport | None,
) -> tuple[GateRuleRecord, ReliabilityReport | None]:
    """Evaluate one rule against *run*, returning its record.

    The reliability report is threaded through rather than recomputed: it is
    built at most once per gate, lazily, only when a rule actually asks for a
    reliability metric.

    This function is shared verbatim by advisory and blocking rules. The
    advisory/blocking distinction is applied by the caller, at the point a
    verdict is *filed* — never at the point it is computed. Two evaluation
    paths would let the two drift, and the drift would be invisible during
    exactly the soak that is supposed to establish trust in a threshold.
    """
    observed: float | None
    if rule.metric in _RELIABILITY_METRICS:
        if reliability_report is None:
            reliability_report = ReliabilityAggregator.aggregate(run.items)
        observed = _reliability_rate(reliability_report, rule.score, rule.metric)
        if observed is None:
            return _record(rule, None, [f"score '{rule.score}' has no {rule.metric}"]), reliability_report
    else:
        agg = run.aggregate.get(rule.score)
        if agg is None:
            return _record(rule, None, [f"score '{rule.score}' not present in results"]), reliability_report
        observed = agg.mean if rule.metric == "mean" else agg.pass_rate
        if observed is None:
            return _record(rule, None, [f"score '{rule.score}' has no {rule.metric}"]), reliability_report

    unmet: list[str] = []
    if rule.min is not None and observed < rule.min:
        unmet.append(f"{rule.score}.{rule.metric}={observed:.3f} below min {rule.min}")
    if rule.max is not None and observed > rule.max:
        unmet.append(f"{rule.score}.{rule.metric}={observed:.3f} above max {rule.max}")
    return _record(rule, observed, unmet), reliability_report


def evaluate_gate(gate: GateConfig | None, run: RunResult) -> GateResult:
    """Turn a run's aggregates into a pass/fail verdict plus an advisory channel.

    Every rule is evaluated identically; ``GateRule.report_only`` decides only
    which list an unmet rule lands in. ``passed`` therefore reads exactly as it
    did before this capability existed: false when, and only when, a rule that
    can block was not met.
    """
    if gate is None or not gate.rules:
        return GateResult(passed=True)

    blocking: list[str] = []
    advisory: list[str] = []
    records: list[GateRuleRecord] = []

    # Checked before any rule: a rule that reads a healthy rate over a reduced
    # sample is worse than no rule, because it looks like evidence. It is filed
    # as blocking whenever any rule could block, and as advisory otherwise --
    # an all-advisory gate that started failing runs on sample reduction would
    # be blocking on a configuration whose whole point is not to block.
    sample_failures = _item_error_failures(gate, run)
    has_blocking_rule = any(not rule.report_only for rule in gate.rules)
    (blocking if has_blocking_rule else advisory).extend(sample_failures)

    # Computed at most once, lazily — only when a rule actually needs it, and
    # reused across every such rule in this gate rather than re-aggregated per rule.
    reliability_report: ReliabilityReport | None = None

    for rule in gate.rules:
        record, reliability_report = _evaluate_rule(rule, run, reliability_report)
        records.append(record)
        if record.met:
            continue
        (advisory if record.advisory else blocking).append(record.detail)

    result = GateResult(passed=not blocking, failures=blocking, advisory=advisory, rules=records)
    logger.info(
        "quality gate evaluated: passed=%s rules=%d blocking_failures=%d advisory_failures=%d",
        result.passed,
        len(records),
        len(blocking),
        len(advisory),
    )
    for detail in advisory:
        # Advisory outcomes are the point of a soak, so they are visible at INFO
        # rather than buried at DEBUG -- but never at WARNING, which would train
        # operators to ignore a level that blocking problems also use.
        logger.info("quality gate (advisory, non-blocking): %s", detail)
    for detail in blocking:
        logger.warning("quality gate failure: %s", detail)
    return result


#: Signature of the seam the engine uses to reach a gate verdict. Takes the run's
#: own gate configuration and the completed result; returns ``None`` when there is
#: nothing to decide, so an ungated run carries no decision and serializes
#: byte-identically to the pre-change payload.
GateEvaluator = Callable[[GateConfig | None, RunResult], GateDecision | None]


def default_gate_evaluator(gate: GateConfig | None, run: RunResult) -> GateDecision | None:
    """The harness's own gate policy: evaluate the configured rules.

    Returns ``None`` -- rather than a vacuously passing decision -- when **no
    gate is configured at all**. A run nobody asked to gate has not "passed a
    gate", and recording that it did would stamp a green verdict onto every
    ungated artifact; omitting the key also keeps such a run's payload
    byte-identical to the pre-change shape.

    A gate that *is* configured but declares no rules still yields a decision,
    passing and empty. That is deliberately not folded into the ``None`` case
    above: ``evaluate_gate`` has always returned a passing result for it, and
    the CLI has always printed ``QUALITY GATE: PASS`` on the strength of that.
    Collapsing the two would silently drop the verdict line for every config
    using the legacy ruleless-gate shape.

    Injected into :class:`~eval_harness.engine.EvalEngine` as the default
    ``gate_evaluator``. The seam is what lets a caller substitute a different
    policy without the engine growing a branch for it.
    """
    if gate is None:
        return None
    return evaluate_gate(gate, run).to_decision()
