"""Proxy-correlation measurement for prediction-powered audit estimates.

Answers the question that governs whether borrowing statistical strength is worth
wiring at all: **how well does a cheap, always-available proxy predict the expensive,
authoritative HUMAN_AUDIT label — on the subsets the gate actually operates over?**

A control-variate estimator (PPI/PPI++) shrinks the variance of a mean by roughly
``1 - rho**2``, so a proxy correlated at ``rho`` is worth an effective-sample multiplier
of ``1 / (1 - rho**2)`` (:func:`agent_core.ppi.effective_n_multiplier`). Two
consequences drive this module's shape:

* A *marginal* correlation is not the operative number. The merge gate conditions on
  ``score >= tau`` and on a single calibration bin, and on those subsets a confidence-like
  proxy is near-constant **by construction** — that is what defines them. Restriction of
  range drives the conditional correlation toward zero, so the gain evaporates exactly
  where it was wanted. This module therefore reports marginal *and* conditional slices
  side by side; the difference between them is the finding.
* Which proxy is used matters more than which estimator is used. Proxies orthogonal to
  the confidence bin (mechanical outcome signals, an independent judge) retain
  conditional variance where confidence does not.

Read-only: nothing here writes to the store or influences a gate decision.

Proxies are pluggable via :class:`ProxyExtractor`, so adding one (for example an LLM
judge's score) needs no change here and no new dependency — ``agent_core`` stays
dependency-free, and external scores arrive through :class:`MappingProxy`.

Run as a module::

    python -m agent_core.proxy_eval --store merge_outcomes.jsonl \
        [--domain-filter agent|human|all] [--judge-scores scores.json] [--format md|json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .calibration import auroc
from .config import ConfigError
from .domains import DOMAIN_FILTERS, in_domain_scope
from .logging_util import debug_span, get_logger
from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from .ppi import (
    PPIConfig,
    PPIEstimate,
    effective_n_multiplier,
    pearson_r,
    ppi_plus_interval,
)

# Re-exported (`X as X` is mypy's explicit re-export form) so the proxies stay importable
# from here after being split into `agent_core.proxies`.
from .proxies import MappingProxy as MappingProxy
from .proxies import PassiveLabelProxy as PassiveLabelProxy
from .proxies import ProxyExtractor as ProxyExtractor
from .proxies import RawConfidenceProxy as RawConfidenceProxy

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProxyEvalConfig:
    """Tunables for the proxy evaluation. No literal appears at a call site."""

    n_bins: int = 10  # bin count for the per-bin conditional slices
    z: float = 1.96  # interval quantile handed to the PPI estimator
    # Floor on slice size before a correlation is reported. Three, not two: any two points
    # are perfectly collinear, so n=2 yields |rho| == 1 by construction and an
    # effective-sample multiplier of ~1/0 -- spectacular precision from two observations.
    min_pairs: int = 3
    # Upper-tail cutoffs for the "gated subset" slices, as quantiles of the proxy. These
    # stand in for candidate `tau` values: the gate only ever auto-merges above one.
    tau_quantiles: tuple[float, ...] = (0.5, 0.75, 0.9)

    def __post_init__(self) -> None:
        if self.n_bins < 1:
            raise ConfigError(f"proxy-eval.n_bins must be >= 1 (got {self.n_bins!r})")
        if not (math.isfinite(self.z) and self.z > 0):
            raise ConfigError(f"proxy-eval.z must be a finite value > 0 (got {self.z!r})")
        if self.min_pairs < 3:
            raise ConfigError(f"proxy-eval.min_pairs must be >= 3 (got {self.min_pairs!r})")
        for q in self.tau_quantiles:
            if not (math.isfinite(q) and 0.0 <= q < 1.0):
                raise ConfigError(
                    f"proxy-eval.tau_quantiles must be finite values in [0, 1) (got {q!r})"
                )


# --- dataset assembly --------------------------------------------------------
@dataclass(frozen=True)
class ProxyPair:
    change_id: str
    domain: str
    proxy: float
    correct: bool


@dataclass(frozen=True)
class ProxyDataset:
    """Labelled pairs plus the unlabelled proxy pool PPI borrows strength from."""

    proxy: str
    labeled: tuple[ProxyPair, ...]
    unlabeled: tuple[float, ...]


def _records_by_change(store: OutcomeStore) -> dict[str, list[OutcomeRecord]]:
    grouped: dict[str, list[OutcomeRecord]] = {}
    for r in store.all():
        grouped.setdefault(r.change_id, []).append(r)
    return grouped


def build_dataset(
    store: OutcomeStore,
    extractor: ProxyExtractor,
    *,
    domain_filter: str = "all",
) -> ProxyDataset:
    """Join each change's proxy value to its authoritative label, if it has one.

    The join is by ``change_id`` across append-only records, because a single record
    carries one label from one source: the mechanical signal and the human verdict are
    *different rows*. Changes with a HUMAN_AUDIT row become labelled pairs; the rest
    contribute their proxy value to the unlabelled pool.
    """
    labeled: list[ProxyPair] = []
    unlabeled: list[float] = []
    # `resolved()` owns the authoritative-label precedence (HUMAN_AUDIT wins, later
    # verdict supersedes). Re-deriving it here by scanning for the *first* audit row got a
    # different answer whenever an early audit row carried `label=None`, silently demoting
    # an audited change into the unlabelled pool -- losing a scarce label and breaking the
    # disjointness the variance formula assumes. The grouping below is still needed
    # because a proxy may read rows `resolved()` collapses away.
    resolved = store.resolved()
    for change_id, records in sorted(_records_by_change(store).items()):
        authoritative = resolved.get(change_id)
        domain = authoritative.domain if authoritative is not None else records[0].domain
        if not in_domain_scope(domain, domain_filter):
            continue
        proxy = extractor.value(change_id, records)
        if proxy is None:
            continue
        if (
            authoritative is not None
            and authoritative.label_source == LabelSource.HUMAN_AUDIT.value
            and authoritative.label is not None
        ):
            labeled.append(ProxyPair(change_id, domain, proxy, bool(authoritative.label)))
        else:
            unlabeled.append(proxy)
    logger.debug(
        "proxy %s: %d labelled pair(s), %d unlabelled value(s) [domain_filter=%s]",
        extractor.name,
        len(labeled),
        len(unlabeled),
        domain_filter,
    )
    return ProxyDataset(extractor.name, tuple(labeled), tuple(unlabeled))


def _standardise(xs: Sequence[float]) -> list[float]:
    """Min-max the proxy into ``[0, 1]``.

    The PPI estimator targets a probability, so it requires a bounded proxy; an external
    judge's scores (the ``--judge-scores`` seam) carry no such contract. Rescaling is
    lossless for this purpose because the estimator's ``lambda`` is scale-free — only the
    proxy's *shape* matters, and a monotone affine map preserves it exactly.
    """
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return [0.0] * len(xs)
    return [(x - lo) / (hi - lo) for x in xs]


# --- analysis ----------------------------------------------------------------
@dataclass(frozen=True)
class SliceCorrelation:
    """Correlation of one proxy with correctness over one slice of the audited set."""

    label: str
    n: int
    rho: float | None
    auroc: float | None
    effective_n: float
    degenerate: str | None


def _analyze_pairs(
    label: str, pairs: Sequence[ProxyPair], cfg: ProxyEvalConfig
) -> SliceCorrelation:
    n = len(pairs)
    if n < cfg.min_pairs:
        return SliceCorrelation(
            label, n, None, None, 1.0, f"insufficient pairs: n={n} < {cfg.min_pairs}"
        )
    xs = [p.proxy for p in pairs]
    ys = [float(p.correct) for p in pairs]
    rho = pearson_r(xs, ys)
    degenerate: str | None = None
    if rho is None:
        # Name the constant side: a constant proxy and a single outcome class are very
        # different findings, and collapsing them into one message loses the diagnosis.
        if len(set(xs)) == 1:
            degenerate = f"constant proxy: value == {xs[0]:.4g} for all {n} records"
        else:
            cls = "correct" if ys[0] == 1.0 else "incorrect"
            degenerate = f"single outcome class: all {n} outcomes are {cls}"
    elif abs(rho) >= 1.0:
        # A textbook-perfect correlation on real audit data is an artifact of a tiny or
        # collinear slice, not a discovery. Reporting its multiplier (1/(1-rho^2) -> the
        # saturation cap) would advertise near-infinite effective samples from a handful
        # of records, which is exactly the false precision this report exists to avoid.
        degenerate = f"perfect correlation on n={n} records: too collinear to be evidence"
        rho = None
    # Withhold AUROC on a degenerate slice, matching `calibration_report.analyze_slice`.
    # A constant proxy cannot rank anything, so its AUROC is 0.5 *by construction* -- and
    # emitting that number is precisely the false precision this module exists to refuse.
    # Both classes being present is necessary for AUROC to be defined, but not sufficient
    # for it to mean anything.
    roc: float | None = None
    if degenerate is None and len({int(y) for y in ys}) == 2:
        roc = auroc(xs, [int(y) for y in ys])
    return SliceCorrelation(label, n, rho, roc, effective_n_multiplier(rho), degenerate)


def _quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Nearest-rank quantile. Deterministic and dependency-free."""
    if not sorted_xs:
        return 0.0
    idx = min(len(sorted_xs) - 1, max(0, math.ceil(q * len(sorted_xs)) - 1))
    return sorted_xs[idx]


@dataclass(frozen=True)
class ProxyReport:
    proxy: str
    n_labeled: int
    n_unlabeled: int
    marginal: SliceCorrelation
    conditional: tuple[SliceCorrelation, ...]
    ppi: PPIEstimate | None


def analyze_dataset(dataset: ProxyDataset, cfg: ProxyEvalConfig | None = None) -> ProxyReport:
    """Marginal + conditional correlation for one proxy, and what PPI++ would buy."""
    cfg = cfg or ProxyEvalConfig()
    pairs = list(dataset.labeled)
    marginal = _analyze_pairs("marginal (all audited)", pairs, cfg)

    conditional: list[SliceCorrelation] = []
    xs_sorted = sorted(p.proxy for p in pairs)
    for q in cfg.tau_quantiles:
        cut = _quantile(xs_sorted, q)
        subset = [p for p in pairs if p.proxy >= cut]
        conditional.append(_analyze_pairs(f"proxy >= q{q:g} ({cut:.4g})", subset, cfg))
    # Bin edges span the proxy's OBSERVED range, not a presumed [0, 1]. Fixed unit edges
    # silently dropped every negative score and swept everything above 1.0 into a bin
    # labelled "[0.9,1)" -- and an external judge's scores (the whole point of the
    # MappingProxy seam) carry no unit-interval contract.
    if xs_sorted and xs_sorted[-1] > xs_sorted[0]:
        span_lo, span_hi = xs_sorted[0], xs_sorted[-1]
        width = (span_hi - span_lo) / cfg.n_bins
        for b in range(cfg.n_bins):
            lo, hi = span_lo + width * b, span_lo + width * (b + 1)
            last = b == cfg.n_bins - 1
            subset = [p for p in pairs if p.proxy >= lo and (p.proxy < hi or last)]
            if subset:
                conditional.append(_analyze_pairs(f"bin [{lo:.4g},{hi:.4g})", subset, cfg))

    ppi: PPIEstimate | None = None
    if pairs:
        # Standardise both pools on the SAME scale before the estimator sees them: it
        # targets a probability and so requires a bounded proxy, while lambda is
        # scale-free, making a shared affine map lossless.
        scaled = _standardise([p.proxy for p in pairs] + list(dataset.unlabeled))
        ppi = ppi_plus_interval(
            [(f, int(p.correct)) for f, p in zip(scaled[: len(pairs)], pairs, strict=True)],
            scaled[len(pairs) :],
            PPIConfig(z=cfg.z),
        )
    return ProxyReport(
        proxy=dataset.proxy,
        n_labeled=len(pairs),
        n_unlabeled=len(dataset.unlabeled),
        marginal=marginal,
        conditional=tuple(conditional),
        ppi=ppi,
    )


def default_extractors(judge_scores: Mapping[str, float] | None = None) -> list[ProxyExtractor]:
    """The proxies evaluated when a caller does not supply its own set."""
    extractors: list[ProxyExtractor] = [RawConfidenceProxy(), PassiveLabelProxy()]
    if judge_scores:
        extractors.append(MappingProxy("judge_score", dict(judge_scores)))
    return extractors


def evaluate_store(
    store: OutcomeStore,
    extractors: Sequence[ProxyExtractor] | None = None,
    cfg: ProxyEvalConfig | None = None,
    *,
    domain_filter: str = "agent",
) -> list[ProxyReport]:
    """Build and analyse a dataset per proxy. Read-only over the store."""
    cfg = cfg or ProxyEvalConfig()
    chosen = list(extractors) if extractors is not None else default_extractors()
    if not store.path.exists():
        logger.warning(
            "outcome store %s does not exist -- reporting empty slices (is --store right?)",
            store.path,
        )
    reports: list[ProxyReport] = []
    with debug_span(logger, "evaluate_store", proxies=len(chosen), domain_filter=domain_filter):
        for extractor in chosen:
            dataset = build_dataset(store, extractor, domain_filter=domain_filter)
            reports.append(analyze_dataset(dataset, cfg))
    return reports


# --- rendering ---------------------------------------------------------------
def _fmt(v: float | None, spec: str = ".4f") -> str:
    return "n/a" if v is None else format(v, spec)


def render_markdown(reports: Sequence[ProxyReport], cfg: ProxyEvalConfig) -> str:
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


# --- CLI ---------------------------------------------------------------------
def _load_judge_scores(path: str | None) -> dict[str, float] | None:
    """Load ``{change_id: score}`` from JSON. The external-proxy seam."""
    if path is None:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"judge scores must be a JSON object of change_id -> score ({path})")
    out: dict[str, float] = {}
    for k, v in raw.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            raise ConfigError(f"judge score for {k!r} must be a finite number (got {v!r})")
        out[str(k)] = float(v)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Proxy-correlation report for audit estimates.")
    ap.add_argument("--store", required=True)
    ap.add_argument("--domain-filter", choices=list(DOMAIN_FILTERS), default="agent")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    defaults = ProxyEvalConfig()
    ap.add_argument("--n-bins", type=int, default=defaults.n_bins)
    ap.add_argument("--z", type=float, default=defaults.z)
    ap.add_argument("--min-pairs", type=int, default=defaults.min_pairs)
    ap.add_argument(
        "--judge-scores",
        default=None,
        help="JSON file of {change_id: score} adding an external proxy (e.g. an LLM judge)",
    )
    ap.add_argument("--output", help="write here instead of stdout")
    args = ap.parse_args(argv)

    try:
        cfg = ProxyEvalConfig(n_bins=args.n_bins, z=args.z, min_pairs=args.min_pairs)
        judge = _load_judge_scores(args.judge_scores)
    except (ConfigError, OSError, json.JSONDecodeError) as exc:
        logger.error("invalid proxy-eval configuration: %s", exc)
        return 2

    reports = evaluate_store(
        OutcomeStore(args.store),
        default_extractors(judge),
        cfg,
        domain_filter=args.domain_filter,
    )
    text = render_json(reports, cfg) if args.format == "json" else render_markdown(reports, cfg)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
