"""Agent-records calibration report (F-043, ADR 0023).

Read-only over the outcome store. Emits ECE, Brier + Murphy decomposition, AUROC,
and selective-abstention with Wilson CIs for agent-domain records, reusing the
metrics in :mod:`agent_core.calibration` unchanged.

Two views, kept strictly separate (invariant I-1):

  * **PRIMARY** — HUMAN_AUDIT records only. These are the unbiased sample that could
    ever feed ``tau``; this is the headline curve.
  * **DIAGNOSTIC** — all labeled records (passive + audit). Marked NOT tau-eligible,
    because ``timeout_clean`` is a weak optimistic positive; useful only for a fuller,
    contaminated picture.

Honest by construction: the proxy calibrates the *proxy heuristic*, not an agent's
belief (ADR 0023 §1), so a slice with no confidence variance, or a single outcome
class, is reported as ``DEGENERATE: <reason>`` rather than a misleading AUROC of 0.5.

``agent_version`` is recovered by joining a resolved record back to its seed record by
``change_id`` (``record_verdict`` does not carry it forward), so no TCB change is needed.

Run as a module::

    python -m agent_core.calibration_report --store merge_outcomes.jsonl \
        [--domain-filter agent|human|all] [--format md|json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .calibration import (
    auroc,
    brier_decomposition,
    brier_score,
    expected_calibration_error,
    selective_risk_coverage,
    wilson_interval,
)
from .config import ConfigError
from .domains import is_agent_domain
from .logging_util import get_logger
from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReportConfig:
    """Calibration-report knobs — documented defaults, not magic numbers at call sites."""

    n_bins: int = 10
    risk_target: float = 0.05  # abstention risk target for the selective-risk summary
    z: float = 1.96  # Wilson-interval z (95% by default)

    def __post_init__(self) -> None:
        if self.n_bins < 1:
            raise ConfigError("calibration-report.n_bins must be >= 1")
        if not 0.0 <= self.risk_target <= 1.0:
            raise ConfigError("calibration-report.risk_target must be in [0, 1]")
        if self.z <= 0:
            raise ConfigError("calibration-report.z must be > 0")


@dataclass(frozen=True)
class SliceReport:
    label: str
    n: int
    n_correct: int
    base_rate: float | None
    base_rate_ci: tuple[float, float] | None
    ece: float | None
    brier: float | None
    reliability: float | None
    resolution: float | None
    uncertainty: float | None
    auroc: float | None
    abstention_at_target: float | None
    risk_target: float
    degenerate: str | None


def analyze_slice(
    pairs: list[tuple[float, bool]],
    label: str,
    *,
    cfg: ReportConfig | None = None,
) -> SliceReport:
    """Compute the calibration metrics for one (confidence, correct) slice.

    ``degenerate`` is set (and ``auroc`` withheld) when the predictor is constant or
    only one outcome class is present — discrimination is undefined, so we say so
    instead of reporting the by-construction 0.5.
    """
    cfg = cfg or ReportConfig()
    n = len(pairs)
    if n == 0:
        return SliceReport(
            label,
            0,
            0,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            cfg.risk_target,
            "no labeled records",
        )
    probs = [p for p, _ in pairs]
    outcomes = [int(b) for _, b in pairs]
    n_correct = sum(outcomes)
    base_rate = n_correct / n
    base_ci = wilson_interval(n_correct, n, cfg.z)
    ece = expected_calibration_error(probs, outcomes, cfg.n_bins)
    brier = brier_score(probs, outcomes)
    dec = brier_decomposition(probs, outcomes, cfg.n_bins)

    degenerate: str | None = None
    auroc_val: float | None = None
    if len(set(probs)) == 1:
        degenerate = f"constant predictor: raw_confidence == {probs[0]:.4g} for all {n} records"
    elif len(set(outcomes)) == 1:
        cls = "correct" if outcomes[0] == 1 else "incorrect"
        degenerate = f"single outcome class: all {n} labels are {cls}"
    else:
        auroc_val = auroc(probs, outcomes)

    points = selective_risk_coverage(probs, outcomes)
    reachable = [cov for cov, risk in points if risk <= cfg.risk_target]
    abstention = 1.0 - (max(reachable) if reachable else 0.0)

    return SliceReport(
        label=label,
        n=n,
        n_correct=n_correct,
        base_rate=base_rate,
        base_rate_ci=base_ci,
        ece=ece,
        brier=brier,
        reliability=dec.reliability,
        resolution=dec.resolution,
        uncertainty=dec.uncertainty,
        auroc=auroc_val,
        abstention_at_target=abstention,
        risk_target=cfg.risk_target,
        degenerate=degenerate,
    )


@dataclass(frozen=True)
class View:
    name: str
    tau_eligible: bool
    slices: list[SliceReport]


@dataclass(frozen=True)
class ReportDoc:
    domain_filter: str
    total_records: int
    resolved_records: int
    by_label_source: dict[str, int]
    views: list[View]


def _agent_version_index(records: list[OutcomeRecord]) -> dict[str, str]:
    """change_id -> agent_version, from whichever record carries it (the seed)."""
    idx: dict[str, str] = {}
    for r in records:
        if r.agent_version:
            idx[r.change_id] = r.agent_version
    return idx


def _in_scope(domain: str, domain_filter: str) -> bool:
    if domain_filter == "agent":
        return is_agent_domain(domain)
    if domain_filter == "human":
        return not is_agent_domain(domain)
    return True


def _build_view(
    name: str,
    tau_eligible: bool,
    records: list[OutcomeRecord],
    av_index: dict[str, str],
    domain_filter: str,
    *,
    cfg: ReportConfig,
) -> View:
    def analyze(pairs: list[tuple[float, bool]], label: str) -> SliceReport:
        return analyze_slice(pairs, label, cfg=cfg)

    slices: list[SliceReport] = [
        analyze(
            [(r.raw_confidence, bool(r.label)) for r in records], f"ALL {domain_filter} domains"
        )
    ]
    by_domain: dict[str, list[OutcomeRecord]] = {}
    for r in records:
        by_domain.setdefault(r.domain, []).append(r)
    for domain in sorted(by_domain):
        slices.append(
            analyze(
                [(r.raw_confidence, bool(r.label)) for r in by_domain[domain]], f"domain: {domain}"
            )
        )

    if domain_filter in ("agent", "all"):
        by_av: dict[str, list[OutcomeRecord]] = {}
        for r in records:
            if is_agent_domain(r.domain):
                by_av.setdefault(av_index.get(r.change_id, "(unknown)"), []).append(r)
        for av in sorted(by_av):
            slices.append(
                analyze(
                    [(r.raw_confidence, bool(r.label)) for r in by_av[av]], f"agent_version: {av}"
                )
            )

    return View(name=name, tau_eligible=tau_eligible, slices=slices)


def build_report(
    store: OutcomeStore,
    *,
    domain_filter: str = "agent",
    cfg: ReportConfig | None = None,
) -> ReportDoc:
    cfg = cfg or ReportConfig()
    if store.path.exists():
        all_records = store.all()
        resolved = store.resolved()
    else:
        all_records = []
        resolved = {}
    av_index = _agent_version_index(all_records)
    by_source = Counter(r.label_source or "pending" for r in resolved.values())

    labeled = [
        r for r in resolved.values() if r.label is not None and _in_scope(r.domain, domain_filter)
    ]
    primary = [r for r in labeled if r.label_source == LabelSource.HUMAN_AUDIT.value]

    views = [
        _build_view(
            "PRIMARY — HUMAN_AUDIT only (tau-relevant)",
            True,
            primary,
            av_index,
            domain_filter,
            cfg=cfg,
        ),
        _build_view(
            "DIAGNOSTIC — all labels incl. weak timeout_clean (NOT tau-eligible)",
            False,
            labeled,
            av_index,
            domain_filter,
            cfg=cfg,
        ),
    ]
    return ReportDoc(
        domain_filter=domain_filter,
        total_records=len(all_records),
        resolved_records=len(resolved),
        by_label_source=dict(sorted(by_source.items())),
        views=views,
    )


# --- rendering ---------------------------------------------------------------
def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.4f}"


def _ci(ci: tuple[float, float] | None) -> str:
    return "—" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def render_markdown(doc: ReportDoc) -> str:
    lines: list[str] = []
    lines.append(f"# Agent-records calibration report (domain-filter: {doc.domain_filter})")
    lines.append("")
    lines.append(
        "> These numbers calibrate a **deterministic proxy** (ADR 0023 §1), not an agent's "
        "belief. The PRIMARY view (HUMAN_AUDIT) is the only tau-relevant one; the DIAGNOSTIC "
        "view mixes in weak optimistic `timeout_clean` labels and is not tau-eligible. At low "
        "N the Wilson CIs are wide — treat this as a proof the pipeline emits a real, "
        "correctly-uncertain number, not a precise calibration."
    )
    lines.append("")
    lines.append(
        f"Store: {doc.total_records} records, {doc.resolved_records} resolved change_ids; "
        f"by label_source: {doc.by_label_source}"
    )
    for view in doc.views:
        lines.append("")
        lines.append(f"## {view.name}")
        lines.append("")
        lines.append(
            "| slice | N | correct | base rate [Wilson 95%] | ECE | Brier |"
            " resolution | AUROC | abstain@risk | note |"
        )
        lines.append("|---|--:|--:|---|--:|--:|--:|--:|--:|---|")
        for s in view.slices:
            auroc_cell = _f(s.auroc) if s.degenerate is None else "—"
            note = s.degenerate or ""
            abstain = (
                "—"
                if s.abstention_at_target is None
                else f"{s.abstention_at_target:.2f}@{s.risk_target:g}"
            )
            lines.append(
                f"| {s.label} | {s.n} | {s.n_correct} | "
                f"{_f(s.base_rate)} {_ci(s.base_rate_ci)} | {_f(s.ece)} | {_f(s.brier)} | "
                f"{_f(s.resolution)} | {auroc_cell} | {abstain} | {note} |"
            )
    lines.append("")
    return "\n".join(lines)


def render_json(doc: ReportDoc) -> str:
    return json.dumps(asdict(doc), sort_keys=True, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent-records calibration report (F-043).")
    ap.add_argument("--store", required=True)
    ap.add_argument("--domain-filter", choices=["agent", "human", "all"], default="agent")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    defaults = ReportConfig()
    ap.add_argument("--n-bins", type=int, default=defaults.n_bins)
    ap.add_argument("--risk-target", type=float, default=defaults.risk_target)
    ap.add_argument("--z", type=float, default=defaults.z)
    ap.add_argument("--output", help="write here instead of stdout")
    args = ap.parse_args(argv)

    doc = build_report(
        OutcomeStore(args.store),
        domain_filter=args.domain_filter,
        cfg=ReportConfig(n_bins=args.n_bins, risk_target=args.risk_target, z=args.z),
    )
    rendered = render_json(doc) if args.format == "json" else render_markdown(doc)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    logger.info(
        "calibration-report: filter=%s total=%d resolved=%d",
        args.domain_filter,
        doc.total_records,
        doc.resolved_records,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
