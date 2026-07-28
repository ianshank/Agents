"""Markdown / JSON rendering for the agent-records calibration report.

Separated from :mod:`agent_core.calibration_report` so presentation changes never touch
the analysis, and so each file stays inside the repo's 500-line budget.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .report_types import PPI_PLUS, ReportDoc


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
    dual = doc.estimator == PPI_PLUS
    if dual:
        lines.append("")
        lines.append(
            "> **Dual estimator.** Both the Wilson interval and a power-tuned "
            "prediction-powered (PPI++) interval are shown, alongside the same-family "
            "classical (lambda=0) interval the reduction is measured against. PPI++ borrows "
            "strength from unaudited records, so it tightens *aggregate* estimates; it does "
            "**not** change any gate decision — the gate still uses Wilson. Where the proxy "
            "is uninformative or the slice is degenerate, PPI++ falls back to Wilson and "
            "says so."
        )
        lines.append("")
        lines.append(
            "> **Unweighted.** The audit sampler's per-domain floor deliberately "
            "over-samples low-volume domains, so an aggregate row pools strata with "
            "different inclusion probabilities. `selection_propensity` is now recorded per "
            "audit, but no estimator applies the `1/p` (Horvitz-Thompson) weight yet — "
            "read cross-domain aggregates as indicative, and per-domain rows as sound."
        )
    for view in doc.views:
        lines.append("")
        lines.append(f"## {view.name}")
        lines.append("")
        # Header, alignment rule and every row are built from ONE column list, so a column
        # can never be added to the header without a matching cell. This replaced
        # positional `str.replace` surgery over hand-written markdown, which happened to
        # line up but would have mis-aligned silently on the next column change.
        columns: list[tuple[str, str]] = [
            ("slice", "---"),
            ("N", "--:"),
            ("correct", "--:"),
            ("base rate [Wilson 95%]", "---"),
        ]
        if dual:
            # The classical (lambda=0) interval is shown alongside: without it the only
            # available reading of "var-reduction" is against the Wilson column, a
            # different interval family — which makes a real gain look like a
            # contradiction whenever PPI++ is visibly wider.
            columns += [
                ("PPI++ 95%", "---"),
                ("classical (λ=0)", "---"),
                ("var-reduction", "--:"),
            ]
        columns += [
            ("ECE", "--:"),
            ("Brier", "--:"),
            ("resolution", "--:"),
            ("AUROC", "--:"),
            ("abstain@risk", "--:"),
            ("note", "---"),
        ]
        lines.append("| " + " | ".join(title for title, _ in columns) + " |")
        lines.append("|" + "|".join(align for _, align in columns) + "|")
        for s in view.slices:
            auroc_cell = _f(s.auroc) if s.degenerate is None else "—"
            note = s.degenerate or ""
            abstain = (
                "—"
                if s.abstention_at_target is None
                else f"{s.abstention_at_target:.2f}@{s.risk_target:g}"
            )
            cells = [
                s.label,
                str(s.n),
                str(s.n_correct),
                f"{_f(s.base_rate)} {_ci(s.base_rate_ci)}",
            ]
            if dual:
                if s.ppi is None:
                    cells += ["—", "—", "—"]
                else:
                    vr = s.ppi.variance_reduction
                    cells += [
                        _ci((s.ppi.lo, s.ppi.hi)),
                        _ci((s.ppi.classical_lo, s.ppi.classical_hi)),
                        "—" if vr is None else f"{vr * 100:.1f}%",
                    ]
                    if s.ppi.degenerate:
                        note = "; ".join(
                            x for x in (note, f"PPI++→Wilson ({s.ppi.degenerate})") if x
                        )
            cells += [
                _f(s.ece),
                _f(s.brier),
                _f(s.resolution),
                auroc_cell,
                abstain,
                note,
            ]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_json(doc: ReportDoc) -> str:
    return json.dumps(asdict(doc), sort_keys=True, indent=2)
