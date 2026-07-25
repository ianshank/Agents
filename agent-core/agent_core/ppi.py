"""Prediction-powered inference (PPI++) and the correlation statistics it rests on.

Split out of :mod:`agent_core.calibration` so each file stays inside the repo's
500-line budget (``scripts/check_size_budget.py``) and so the control-variate machinery
is separable from the calibration metrics it complements.

The estimator answers: *given a few expensive authoritative labels and many cheap proxy
predictions, how tightly can the mean outcome rate be bounded?* It is a control variate —

    theta(lambda) = mean_L(Y) + lambda * (mean_U(f) - mean_L(f))

— with ``lambda`` tuned to minimise variance. ``lambda = 0`` is exactly the classical
labelled-only estimator, so the tuned form is asymptotically never worse (PPI++).

Fail-closed by construction: every path that cannot support a trustworthy normal
approximation returns the **Wilson** interval and says why. An interval we cannot trust
must never render as the tightest one on the page.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .calibration import wilson_interval
from .logging_util import get_logger

logger = get_logger(__name__)


# --- moment helpers ----------------------------------------------------------
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _variance(xs: Sequence[float], ddof: int = 1) -> float:
    """Sample variance. Returns 0.0 when fewer than ``ddof + 1`` points exist.

    Squaring a large deviation can exceed the float range, which CPython raises on rather
    than saturating. An unrepresentable spread is reported as ``inf`` so callers reject it
    through their existing finiteness guards instead of crashing on a valid input.
    """
    n = len(xs)
    if n - ddof < 1:
        return 0.0
    mu = _mean(xs)
    try:
        return sum((x - mu) ** 2 for x in xs) / (n - ddof)
    except OverflowError:
        return math.inf


def _covariance(xs: Sequence[float], ys: Sequence[float], ddof: int = 1) -> float:
    n = len(xs)
    if n - ddof < 1:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    try:
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (n - ddof)
    except OverflowError:
        return math.inf


def pearson_r(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation, or ``None`` when it is undefined.

    ``None`` rather than ``0.0``: a constant series makes correlation *undefined*, not
    zero, and reporting the difference is the whole point of the degeneracy handling
    elsewhere. Result is clamped to ``[-1, 1]`` against float drift.
    """
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have equal length")
    if len(xs) < 2:
        return None
    vx, vy = _variance(xs), _variance(ys)
    if vx <= 0.0 or vy <= 0.0:
        return None
    # Root each variance BEFORE multiplying. ``sqrt(vx * vy)`` looks equivalent but the
    # product underflows to exactly 0.0 for tiny-but-positive variances (two points
    # ~1e-83 apart give vx*vy ~1e-331, below the smallest subnormal), and the division
    # then raises ZeroDivisionError. Rooting first keeps both factors representable.
    denom = math.sqrt(vx) * math.sqrt(vy)
    if denom <= 0.0 or not math.isfinite(denom):
        return None
    r = _covariance(xs, ys) / denom
    if not math.isfinite(r):
        return None
    return max(-1.0, min(1.0, r))


@dataclass(frozen=True)
class CorrelationConfig:
    """Knobs for turning a correlation into an effective-sample claim."""

    # Ceiling on the reported 1/(1-rho^2) multiplier. This is a *credibility* policy, not
    # a mathematical constant: the ratio diverges as |rho| -> 1, and printing "1000000x"
    # off a handful of records is precisely the false precision this package exists to
    # avoid. Callers that genuinely want the raw ratio can raise it.
    max_effective_n: float = 100.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.max_effective_n) and self.max_effective_n >= 1.0):
            raise ValueError(
                f"correlation.max_effective_n must be a finite value >= 1 "
                f"(got {self.max_effective_n!r})"
            )


def effective_n_multiplier(rho: float | None, cfg: CorrelationConfig | None = None) -> float:
    """Asymptotic ``n_eff / n`` for a control-variate estimator: ``1 / (1 - rho^2)``.

    How much labelling effort a proxy of correlation ``rho`` is worth. Returns ``1.0`` (no
    gain) for an undefined correlation and saturates at ``cfg.max_effective_n`` rather
    than diverging — a proxy that perfect would mean no labels were needed at all, which
    is never the regime this package operates in.
    """
    cfg = cfg or CorrelationConfig()
    if rho is None:
        return 1.0
    if not -1.0 <= rho <= 1.0:
        raise ValueError(f"rho must be in [-1, 1] (got {rho!r})")
    denom = 1.0 - rho * rho
    if denom <= 0.0:
        return cfg.max_effective_n
    return min(cfg.max_effective_n, 1.0 / denom)


# --- PPI++ -------------------------------------------------------------------
@dataclass(frozen=True)
class PPIConfig:
    """Tunables for the prediction-powered interval. No literal appears at a call site."""

    z: float = 1.96  # normal-approximation quantile (95% by default)
    lambda_min: float = 0.0  # clamp floor; 0 => classical labelled-only estimator
    lambda_max: float = 1.0  # clamp ceiling; 1 => vanilla (untuned) PPI
    # Floor on the labelled sample. The interval is a Wald-type normal approximation and
    # `lambda` is fitted from these same points, so coverage degrades at small n; below
    # this the estimator refuses and falls back to Wilson. Measured coverage informs the
    # default -- see tests/test_ppi.py::test_coverage_is_near_nominal.
    min_labeled: int = 10
    # Proxy values must lie in this range. The estimator itself is scale-free, but the
    # target is a *probability*, so an unbounded proxy can push the point estimate outside
    # [0, 1] and make the clipped interval meaningless. Callers standardise first.
    proxy_lo: float = 0.0
    proxy_hi: float = 1.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.z) and self.z > 0):
            raise ValueError(f"ppi.z must be a finite value > 0 (got {self.z!r})")
        if not (math.isfinite(self.lambda_min) and math.isfinite(self.lambda_max)):
            raise ValueError("ppi.lambda_min/lambda_max must be finite")
        if self.lambda_min > self.lambda_max:
            raise ValueError(
                f"ppi.lambda_min must be <= lambda_max (got {self.lambda_min!r} > "
                f"{self.lambda_max!r})"
            )
        if self.min_labeled < 2:
            raise ValueError(f"ppi.min_labeled must be >= 2 (got {self.min_labeled!r})")
        if not (math.isfinite(self.proxy_lo) and math.isfinite(self.proxy_hi)):
            raise ValueError("ppi.proxy_lo/proxy_hi must be finite")
        if self.proxy_lo >= self.proxy_hi:
            raise ValueError(
                f"ppi.proxy_lo must be < proxy_hi (got {self.proxy_lo!r} >= {self.proxy_hi!r})"
            )


@dataclass(frozen=True)
class PPIEstimate:
    """A prediction-powered mean estimate and its interval.

    ``se``/``se_classical`` are the standard errors the interval was built from. They are
    carried explicitly because :attr:`variance_reduction` MUST be derived from them: the
    rendered bounds are clipped to ``[0, 1]``, and a ratio of clipped widths measures how
    close the estimate sits to a boundary, not how much variance the proxy removed. Doing
    it the obvious way over-reported a 3% gain as 94%.
    """

    point: float
    lo: float
    hi: float
    lam: float
    n_labeled: int
    n_unlabeled: int
    classical_lo: float
    classical_hi: float
    se: float | None = None
    se_classical: float | None = None
    degenerate: str | None = None

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2.0

    @property
    def classical_half_width(self) -> float:
        return (self.classical_hi - self.classical_lo) / 2.0

    @property
    def variance_reduction(self) -> float | None:
        """Fraction of the classical variance the proxy removed, or ``None``.

        ``None`` when there is no trustworthy comparison to make (a degenerate estimate,
        or an undefined classical SE). A *negative* result is returned as-is rather than
        floored at zero: PPI++ can genuinely widen the interval when the unlabeled pool's
        proxy spread greatly exceeds the labelled pool's, and silently reporting that as
        "no gain" would hide a real regression.
        """
        if self.degenerate is not None or self.se is None or self.se_classical is None:
            return None
        if self.se_classical <= 0.0:
            return None
        ratio = self.se / self.se_classical
        return 1.0 - ratio * ratio


def ppi_plus_interval(
    labeled: Sequence[tuple[float, int]],
    unlabeled_proxy: Sequence[float],
    cfg: PPIConfig | None = None,
) -> PPIEstimate:
    """Power-tuned prediction-powered interval for a mean outcome rate.

    ``labeled`` pairs each authoritative outcome with the proxy's value for the same unit;
    ``unlabeled_proxy`` holds proxy values for units with no authoritative label. Proxy
    values must lie within ``[cfg.proxy_lo, cfg.proxy_hi]`` — the estimator is scale-free
    but the estimand is a probability, so an out-of-range proxy can drive the point
    estimate outside ``[0, 1]``.

    Fail-closed: too few labels, a single outcome class (zero labelled variance, which
    would collapse the interval to a false-certainty point), a constant proxy, an
    out-of-contract proxy, or no unlabeled data all return the **Wilson** interval with
    ``degenerate`` explaining why.
    """
    cfg = cfg or PPIConfig()
    n = len(labeled)
    outcomes = [o for _, o in labeled]
    for o in outcomes:
        if o not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {o}")
    k = sum(outcomes)
    fallback_lo, fallback_hi = wilson_interval(k, n, cfg.z)
    # Pin the fallback point inside its own interval. At k == n the Wilson upper bound can
    # land one ULP below 1.0 (the `min(1.0, centre + half)` rounds down) while k/n is
    # exactly 1.0, leaving the reported point marginally outside the interval it belongs to.
    point_fallback = min(max((k / n) if n else 0.0, fallback_lo), fallback_hi)

    def _degenerate(reason: str) -> PPIEstimate:
        logger.debug(
            "prediction-powered interval unavailable (%s); falling back to the Wilson "
            "interval on %d labelled record(s)",
            reason,
            n,
        )
        return PPIEstimate(
            point=point_fallback,
            lo=fallback_lo,
            hi=fallback_hi,
            lam=0.0,
            n_labeled=n,
            n_unlabeled=len(unlabeled_proxy),
            classical_lo=fallback_lo,
            classical_hi=fallback_hi,
            degenerate=reason,
        )

    if n < cfg.min_labeled:
        return _degenerate(f"insufficient labelled samples: n={n} < {cfg.min_labeled}")
    if len(set(outcomes)) == 1:
        cls = "correct" if outcomes[0] == 1 else "incorrect"
        return _degenerate(f"single outcome class: all {n} labelled outcomes are {cls}")

    big_n = len(unlabeled_proxy)
    if big_n == 0:
        return _degenerate("no unlabeled proxy values: nothing to borrow strength from")

    proxies = [p for p, _ in labeled]
    out_of_range = [
        p for p in (*proxies, *unlabeled_proxy) if not cfg.proxy_lo <= p <= cfg.proxy_hi
    ]
    if out_of_range:
        return _degenerate(
            f"proxy outside [{cfg.proxy_lo:g}, {cfg.proxy_hi:g}]: "
            f"{len(out_of_range)} value(s), e.g. {out_of_range[0]:.4g} -- standardise first"
        )

    ys = [float(o) for o in outcomes]
    var_f_l = _variance(proxies)
    if var_f_l <= 0.0:
        return _degenerate(f"constant proxy: value == {proxies[0]:.4g} for all {n} records")
    if not math.isfinite(var_f_l):
        return _degenerate("proxy variance is not representable as a float")

    # A single unlabeled draw has no variance estimate; substituting the labelled pool's
    # spread is the conservative choice (asserting zero would claim a one-observation mean
    # is noiseless and make the interval too narrow).
    var_u_f = _variance(unlabeled_proxy) if big_n >= 2 else var_f_l
    var_y = _variance(ys)
    cov_yf = _covariance(proxies, ys)
    # Exact variance-minimising lambda for the interval actually emitted below:
    # d/dlambda [ (v_Y - 2*lambda*c + lambda^2*v_fL)/n + lambda^2*v_fU/N ] = 0.
    # The familiar PPI++ form c/(v_fL*(1 + n/N)) is this under v_fU == v_fL; using the
    # measured v_fU costs nothing because it is already computed.
    lam_denom = var_f_l + n * var_u_f / big_n
    lam = 0.0 if lam_denom <= 0.0 else cov_yf / lam_denom
    lam = max(cfg.lambda_min, min(cfg.lambda_max, lam))

    # lambda was fitted from these same n points, so the residual spread costs a second
    # degree of freedom. With ddof=1 the variance is understated by (n-1)/(n-2) -- 2x at
    # n=3 -- which is what pushed small-n coverage below nominal.
    #
    # Except at lambda == 0: the estimator is then exactly the classical mean with no free
    # parameter, so charging a second dof would make `se != se_classical` and quietly break
    # the "lambda = 0 recovers the classical estimator" guarantee the whole no-worse-than-
    # classical argument rests on.
    resid_ddof = 1 if lam == 0.0 else 2
    var_resid = _variance([y - lam * f for f, y in zip(proxies, ys, strict=True)], ddof=resid_ddof)
    var_point = max(0.0, var_resid) / n + (lam * lam) * var_u_f / big_n
    se = math.sqrt(var_point)
    se_classical = math.sqrt(var_y / n)
    if not (math.isfinite(se) and math.isfinite(se_classical)):
        return _degenerate("standard error is not representable as a float")

    # Clamp the POINT first, then derive the bounds from it. Clipping lo and hi
    # independently of an out-of-range point produced inverted intervals (lo > hi) that
    # rendered as `[1.240, 1.000]` with no degeneracy flag.
    point = max(0.0, min(1.0, _mean(ys) + lam * (_mean(unlabeled_proxy) - _mean(proxies))))
    classical_point = max(0.0, min(1.0, _mean(ys)))
    lo, hi = max(0.0, point - cfg.z * se), min(1.0, point + cfg.z * se)
    c_lo = max(0.0, classical_point - cfg.z * se_classical)
    c_hi = min(1.0, classical_point + cfg.z * se_classical)
    logger.debug(
        "ppi++: n=%d N=%d lam=%.6f point=%.6f se=%.6f se_classical=%.6f",
        n,
        big_n,
        lam,
        point,
        se,
        se_classical,
    )
    return PPIEstimate(
        point=point,
        lo=min(lo, hi),
        hi=max(lo, hi),
        lam=lam,
        n_labeled=n,
        n_unlabeled=big_n,
        classical_lo=min(c_lo, c_hi),
        classical_hi=max(c_lo, c_hi),
        se=se,
        se_classical=se_classical,
    )
