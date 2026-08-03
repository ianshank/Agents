"""Rendering for proxy-correlation reports.

Formats proxy analysis results as markdown or JSON for human and programmatic consumption.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict

from .proxy_analysis import ProxyEvalConfig, ProxyReport


def _fmt(v: float | None, spec: str = ".4f") -> str:
    """Format a float or None as string."""
    return "n/a" if v is None else format(v, spec)


def render_markdown(reports: Sequence[ProxyReport], cfg: ProxyEvalConfig) -> str:
    """Render proxy analysis results as markdown.

    Args:
        reports: Sequence of ProxyReport objects to render
        cfg: Configuration used in analysis

    Returns:
        Markdown-formatted report string
    """
    lines = [
        "# Proxy-correlation report",
        "",
        "How much a cheap proxy could tighten audit-based estimates. `n_eff` is the",
        "asymptotic effective-sample multiplier `1/(1-rho^2)`: the factor by which a",
        "proxy of that correlation stretches a fixed audit budget.",
        "",
        "**Read the conditional rows, not just the marginal one.** The gate conditions on",
        "`score >= tau` and on a single bin; a proxy that only correlates marginally buys",
        "nothing there.",
        "",
    ]
    for rep in reports:
        lines += [
            f"## proxy: `{rep.proxy}`",
            "",
            f"- labelled (audited) pairs: **{rep.n_labeled}**",
            f"- unlabelled proxy values: **{rep.n_unlabeled}**",
            "",
            "| slice | n | rho | AUROC | n_eff | note |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for sl in (rep.marginal, *rep.conditional):
            lines.append(
                f"| {sl.label} | {sl.n} | {_fmt(sl.rho)} | {_fmt(sl.auroc)} | "
                f"{_fmt(sl.effective_n, '.2f')}x | {sl.degenerate or ''} |"
            )
        lines.append("")
        if rep.ppi is not None:
            p = rep.ppi
            lines += [
                f"PPI++ on this proxy: point **{p.point:.4f}**, interval "
                f"[{p.lo:.4f}, {p.hi:.4f}] (lambda={p.lam:.4f}, n={p.n_labeled}, "
                f"N={p.n_unlabeled}).",
                "",
                f"Same-family classical (lambda=0) interval: [{p.classical_lo:.4f}, "
                f"{p.classical_hi:.4f}] -> variance reduction "
                + (
                    "**n/a** (no trustworthy comparison)."
                    if p.variance_reduction is None
                    else f"**{p.variance_reduction * 100:.1f}%** (from the standard errors, "
                    "not the clipped bounds)."
                ),
                "",
            ]
            if p.degenerate:
                lines += [f"> DEGENERATE: {p.degenerate} (interval shown is Wilson).", ""]
    lines += [
        "---",
        "",
        f"Config: n_bins={cfg.n_bins}, z={cfg.z}, min_pairs={cfg.min_pairs}, "
        f"tau_quantiles={list(cfg.tau_quantiles)}.",
        "",
    ]
    return "\n".join(lines)


def render_json(reports: Sequence[ProxyReport], cfg: ProxyEvalConfig) -> str:
    """Render proxy analysis results as JSON.

    Args:
        reports: Sequence of ProxyReport objects to render
        cfg: Configuration used in analysis

    Returns:
        JSON-formatted report string
    """
    payload = {
        "config": asdict(cfg),
        "proxies": [
            {
                "proxy": r.proxy,
                "n_labeled": r.n_labeled,
                "n_unlabeled": r.n_unlabeled,
                "marginal": asdict(r.marginal),
                "conditional": [asdict(s) for s in r.conditional],
                "ppi": (
                    None
                    if r.ppi is None
                    else {
                        **asdict(r.ppi),
                        "half_width": r.ppi.half_width,
                        "classical_half_width": r.ppi.classical_half_width,
                        "variance_reduction": r.ppi.variance_reduction,
                    }
                ),
            }
            for r in reports
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = [
    "render_json",
    "render_markdown",
]
