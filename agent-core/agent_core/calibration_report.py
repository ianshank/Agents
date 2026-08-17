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
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .calibration import (
    auroc,
    brier_decomposition,
    brier_score,
    expected_calibration_error,
    selective_risk_coverage,
    wilson_interval,
)

# Re-exported (mypy's explicit `X as X` form) so the rendering entry points stay
# importable from here after the presentation split.
from .calibration_report_render import render_json as render_json
from .calibration_report_render import render_markdown as render_markdown
from .config import ConfigError
from .domains import DOMAIN_FILTERS, in_domain_scope, is_agent_domain
from .logging_util import configure_logging, get_logger
from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from .ppi import PPIConfig, ppi_plus_interval
from .report_types import (
    ESTIMATORS,
    PPI_PLUS,
    WILSON,
    ReportConfig,
    ReportDoc,
    SliceReport,
    View,
)

logger = get_logger(__name__)

# This module was split into analysis (here), shared types (`report_types`) and
# presentation (`calibration_report_render`) to stay inside the repo's file-size budget.
# The split is internal: every name callers already imported from here still resolves
# from here, and declaring them explicitly is what keeps that a promise (mypy treats an
# `__all__` entry as an explicit re-export, and the public-surface guard freezes it).
__all__ = [
    "ESTIMATORS",
    "PPI_PLUS",
    "WILSON",
    "ReportConfig",
    "ReportDoc",
    "SliceReport",
    "View",
    "analyze_slice",
    "build_report",
    "main",
    "render_json",
    "render_markdown",
]


def analyze_slice(
    pairs: list[tuple[float, bool]],
    label: str,
    *,
    cfg: ReportConfig | None = None,
    unlabeled_proxy: Sequence[float] = (),
) -> SliceReport:
    """Compute the calibration metrics for one (confidence, correct) slice.

    ``degenerate`` is set (and ``auroc`` withheld) when the predictor is constant or
    only one outcome class is present — discrimination is undefined, so we say so
    instead of reporting the by-construction 0.5.

    ``unlabeled_proxy`` carries the confidence values of records this slice could *not*
    authoritatively label. It is used only by the ``ppi++`` estimator, which borrows
    strength from them; the Wilson interval is computed identically either way, so the
    default path is unchanged.
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

    ppi = (
        ppi_plus_interval(
            list(zip(probs, outcomes, strict=True)), unlabeled_proxy, PPIConfig(z=cfg.z)
        )
        if cfg.estimator == PPI_PLUS
        else None
    )

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
        ppi=ppi,
    )


def _agent_version_index(records: list[OutcomeRecord]) -> dict[str, str]:
    """change_id -> agent_version, from whichever record carries it (the seed)."""
    idx: dict[str, str] = {}
    for r in records:
        if r.agent_version:
            idx[r.change_id] = r.agent_version
    return idx


def _in_scope(domain: str, domain_filter: str) -> bool:
    """Thin alias for the canonical predicate in :mod:`agent_core.domains`."""
    return in_domain_scope(domain, domain_filter)


def _build_view(
    name: str,
    tau_eligible: bool,
    records: list[OutcomeRecord],
    av_index: dict[str, str],
    domain_filter: str,
    *,
    cfg: ReportConfig,
    unlabeled: Sequence[OutcomeRecord] = (),
) -> View:
    """Build one view's slices.

    ``unlabeled`` are the in-scope records this view could not authoritatively label.
    Each slice is paired with the *same* grouping of that pool, so a per-domain interval
    borrows strength only from that domain — never from the whole store.
    """

    def analyze(
        pairs: list[tuple[float, bool]], label: str, pool: Sequence[OutcomeRecord]
    ) -> SliceReport:
        return analyze_slice(
            pairs, label, cfg=cfg, unlabeled_proxy=[r.raw_confidence for r in pool]
        )

    slices: list[SliceReport] = [
        analyze(
            [(r.raw_confidence, bool(r.label)) for r in records],
            f"ALL {domain_filter} domains",
            unlabeled,
        )
    ]
    by_domain: dict[str, list[OutcomeRecord]] = {}
    for r in records:
        by_domain.setdefault(r.domain, []).append(r)
    unlabeled_by_domain: dict[str, list[OutcomeRecord]] = {}
    for r in unlabeled:
        unlabeled_by_domain.setdefault(r.domain, []).append(r)
    for domain in sorted(by_domain):
        slices.append(
            analyze(
                [(r.raw_confidence, bool(r.label)) for r in by_domain[domain]],
                f"domain: {domain}",
                unlabeled_by_domain.get(domain, []),
            )
        )

    if domain_filter in ("agent", "all"):
        by_av: dict[str, list[OutcomeRecord]] = {}
        for r in records:
            if is_agent_domain(r.domain):
                by_av.setdefault(av_index.get(r.change_id, "(unknown)"), []).append(r)
        unlabeled_by_av: dict[str, list[OutcomeRecord]] = {}
        for r in unlabeled:
            if is_agent_domain(r.domain):
                unlabeled_by_av.setdefault(av_index.get(r.change_id, "(unknown)"), []).append(r)
        for av in sorted(by_av):
            slices.append(
                analyze(
                    [(r.raw_confidence, bool(r.label)) for r in by_av[av]],
                    f"agent_version: {av}",
                    unlabeled_by_av.get(av, []),
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
        # Disambiguate "no data yet" from "wrong --store / pull misconfigured": an empty
        # report over a nonexistent path is a common operator foot-gun worth a breadcrumb.
        logger.warning(
            "calibration-report: store %s does not exist; emitting an empty report", store.path
        )
        all_records = []
        resolved = {}
    av_index = _agent_version_index(all_records)
    by_source = Counter(r.label_source or "pending" for r in resolved.values())

    labeled = [
        r for r in resolved.values() if r.label is not None and _in_scope(r.domain, domain_filter)
    ]
    primary = [r for r in labeled if r.label_source == LabelSource.HUMAN_AUDIT.value]

    # The unlabeled pool differs per view, because "unlabeled" means "carries no label this
    # view would trust": for PRIMARY that includes every passively-labelled record, which is
    # exactly the large N a prediction-powered estimator borrows from.
    in_scope = [r for r in resolved.values() if _in_scope(r.domain, domain_filter)]
    primary_ids = {r.change_id for r in primary}
    labeled_ids = {r.change_id for r in labeled}
    unlabeled_primary = [r for r in in_scope if r.change_id not in primary_ids]
    unlabeled_diagnostic = [r for r in in_scope if r.change_id not in labeled_ids]

    views = [
        _build_view(
            "PRIMARY — HUMAN_AUDIT only (tau-relevant)",
            True,
            primary,
            av_index,
            domain_filter,
            cfg=cfg,
            unlabeled=unlabeled_primary,
        ),
        _build_view(
            "DIAGNOSTIC — all labels incl. weak timeout_clean (NOT tau-eligible)",
            False,
            labeled,
            av_index,
            domain_filter,
            cfg=cfg,
            unlabeled=unlabeled_diagnostic,
        ),
    ]
    return ReportDoc(
        domain_filter=domain_filter,
        total_records=len(all_records),
        resolved_records=len(resolved),
        by_label_source=dict(sorted(by_source.items())),
        views=views,
        estimator=cfg.estimator,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Agent-records calibration report (F-043).")
    ap.add_argument("--store", required=True)
    ap.add_argument("--domain-filter", choices=list(DOMAIN_FILTERS), default="agent")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    defaults = ReportConfig()
    ap.add_argument("--n-bins", type=int, default=defaults.n_bins)
    ap.add_argument("--risk-target", type=float, default=defaults.risk_target)
    ap.add_argument("--z", type=float, default=defaults.z)
    ap.add_argument(
        "--estimator",
        choices=list(ESTIMATORS),
        default=defaults.estimator,
        help="interval estimator for the base rate; 'ppi++' additionally reports a "
        "prediction-powered interval alongside Wilson (report-only, never the gate)",
    )
    ap.add_argument("--output", help="write here instead of stdout")
    args = ap.parse_args(argv)
    configure_logging(level="INFO")

    # A bad --n-bins/--risk-target/--z is an operator error, not a bug: surface it as a
    # clean message + exit 2, not an unhandled ReportConfig.__post_init__ traceback.
    try:
        cfg = ReportConfig(
            n_bins=args.n_bins,
            risk_target=args.risk_target,
            z=args.z,
            estimator=args.estimator,
        )
    except ConfigError as exc:
        logger.error("calibration-report: %s", exc)
        return 2

    doc = build_report(OutcomeStore(args.store), domain_filter=args.domain_filter, cfg=cfg)
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
