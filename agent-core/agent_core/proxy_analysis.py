"""Statistical analysis for proxy-correlation measurement.

Computes correlations, AUROC, and PPI++ estimates for proxy effectiveness
on labeled and stratified subsets.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .calibration import auroc
from .config import ConfigError
from .logging_util import get_logger
from .ppi import PPIConfig, PPIEstimate, effective_n_multiplier, pearson_r, ppi_plus_interval
from .proxy_dataset import ProxyDataset, ProxyPair, _standardise

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
    """Analyze correlation between proxy and correctness for a slice of pairs."""
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
    """Complete proxy analysis: marginal, conditional, and PPI++ estimates."""

    proxy: str
    n_labeled: int
    n_unlabeled: int
    marginal: SliceCorrelation
    conditional: tuple[SliceCorrelation, ...]
    ppi: PPIEstimate | None


def analyze_dataset(dataset: ProxyDataset, cfg: ProxyEvalConfig | None = None) -> ProxyReport:
    """Marginal + conditional correlation for one proxy, and what PPI++ would buy.

    Args:
        dataset: ProxyDataset with labeled pairs and unlabeled values
        cfg: Configuration for analysis. If None, uses defaults.

    Returns:
        ProxyReport with marginal, conditional, and PPI++ results
    """
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


__all__ = [
    "ProxyEvalConfig",
    "ProxyReport",
    "SliceCorrelation",
    "analyze_dataset",
]
