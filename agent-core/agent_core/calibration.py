"""Calibration measurement.

Pure, dependency-free implementations of the metrics needed to validate that
confidence labels mean what they claim: reliability bins (with Wilson CIs), ECE,
MCE, Brier score and its Murphy decomposition, AUROC (the resolution check that
keeps calibration from being a vanity metric), and selective risk/coverage for
abstention. Plus an isotonic recalibrator (PAV) behind a stable ``Calibrator``
protocol so temperature scaling could swap in later.

Inputs are plain sequences of floats/ints; targets come from
:class:`CalibrationConfig`, never hardcoded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .logging_util import get_logger

logger = get_logger(__name__)


def _check_pairs(probs: Sequence[float], outcomes: Sequence[int]) -> None:
    if len(probs) != len(outcomes):
        raise ValueError("probs and outcomes must have equal length")
    if not probs:
        raise ValueError("empty input")
    for p in probs:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"probability out of range: {p}")
    for o in outcomes:
        if o not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {o}")


# --- reliability bins --------------------------------------------------------
@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    count: int
    mean_conf: float
    accuracy: float
    ci_low: float
    ci_high: float

    @property
    def is_populated(self) -> bool:
        """False for empty bins (whose mean_conf/accuracy are NaN sentinels)."""
        return self.count > 0


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (no normal-approx blow-up)."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (phat + z2 / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def reliability_bins(
    probs: Sequence[float],
    outcomes: Sequence[int],
    n_bins: int = 10,
    z: float = 1.96,
) -> list[Bin]:
    _check_pairs(probs, outcomes)
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    edges = [i / n_bins for i in range(n_bins + 1)]
    bins: list[Bin] = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        # last bin is closed on the right to capture p == 1.0
        if b == n_bins - 1:
            members = [(p, o) for p, o in zip(probs, outcomes, strict=False) if lo <= p <= hi]
        else:
            members = [(p, o) for p, o in zip(probs, outcomes, strict=False) if lo <= p < hi]
        count = len(members)
        if count == 0:
            bins.append(Bin(lo, hi, 0, float("nan"), float("nan"), 0.0, 0.0))
            continue
        mean_conf = sum(p for p, _ in members) / count
        correct = sum(o for _, o in members)
        accuracy = correct / count
        ci_low, ci_high = wilson_interval(correct, count, z)
        bins.append(Bin(lo, hi, count, mean_conf, accuracy, ci_low, ci_high))
    return bins


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> float:
    total = len(probs)
    ece = 0.0
    for b in reliability_bins(probs, outcomes, n_bins):
        if b.count == 0:
            continue
        ece += (b.count / total) * abs(b.accuracy - b.mean_conf)
    return ece


def maximum_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> float:
    gaps = [
        abs(b.accuracy - b.mean_conf)
        for b in reliability_bins(probs, outcomes, n_bins)
        if b.count > 0
    ]
    return max(gaps) if gaps else 0.0


# --- Brier + Murphy decomposition -------------------------------------------
def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    _check_pairs(probs, outcomes)
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes, strict=False)) / len(probs)


@dataclass(frozen=True)
class BrierDecomposition:
    reliability: float
    resolution: float
    uncertainty: float

    @property
    def reconstructed(self) -> float:
        return self.reliability - self.resolution + self.uncertainty


def brier_decomposition(
    probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10
) -> BrierDecomposition:
    """Murphy decomposition: Brier = Reliability - Resolution + Uncertainty.

    Exact for forecasts that are constant within each bin; otherwise it equals
    the Brier of the binned forecasts.
    """
    _check_pairs(probs, outcomes)
    n = len(probs)
    base_rate = sum(outcomes) / n
    reliability = 0.0
    resolution = 0.0
    for b in reliability_bins(probs, outcomes, n_bins):
        if b.count == 0:
            continue
        reliability += b.count * (b.mean_conf - b.accuracy) ** 2
        resolution += b.count * (b.accuracy - base_rate) ** 2
    reliability /= n
    resolution /= n
    uncertainty = base_rate * (1 - base_rate)
    return BrierDecomposition(reliability, resolution, uncertainty)


# --- AUROC (resolution / discrimination) ------------------------------------
def auroc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Area under ROC via the rank (Mann-Whitney U) identity, tie-aware."""
    if len(scores) != len(labels):
        raise ValueError("scores and labels must have equal length")
    if any(y not in (0, 1) for y in labels):
        raise ValueError("labels must be binary (0 or 1)")
    pos = [s for s, y in zip(scores, labels, strict=False) if y == 1]
    neg = [s for s, y in zip(scores, labels, strict=False) if y == 0]
    if not pos or not neg:
        raise ValueError("AUROC undefined without both classes present")
    # average ranks (1-based) to handle ties
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    rank_sum_pos = sum(r for r, y in zip(ranks, labels, strict=False) if y == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


# --- selective prediction (abstention) --------------------------------------
def selective_risk_coverage(
    probs: Sequence[float], outcomes: Sequence[int]
) -> list[tuple[float, float]]:
    """Return (coverage, risk) points as the commit threshold sweeps high->low.

    coverage = fraction committed; risk = error rate among committed. Coverage is
    non-decreasing as the threshold drops.
    """
    _check_pairs(probs, outcomes)
    n = len(probs)
    order = sorted(range(n), key=lambda i: probs[i], reverse=True)
    errors = 0
    committed = 0
    points: list[tuple[float, float]] = []
    i = 0
    while i < len(order):
        # advance through the entire tie group (same probability threshold)
        # so that tied items are committed as one step, not in input order.
        tie_prob = probs[order[i]]
        while i < len(order) and probs[order[i]] == tie_prob:
            committed += 1
            if outcomes[order[i]] == 0:
                errors += 1
            i += 1
        # emit one point per unique threshold
        points.append((committed / n, errors / committed))
    return points


# --- shared moment helpers ---------------------------------------------------
# Smallest denominator tolerated before a variance ratio is treated as saturated.
_MIN_VARIANCE_DENOM = 1e-12


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
    """Pearson correlation, or ``None`` when either series is constant.

    ``None`` rather than ``0.0``: a constant series makes correlation *undefined*, not
    zero, and reporting the difference is the whole point of the degeneracy handling
    elsewhere in this module. Result is clamped to ``[-1, 1]`` against float drift.
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


def effective_n_multiplier(rho: float | None) -> float:
    """Asymptotic ``n_eff / n`` for a control-variate estimator: ``1 / (1 - rho^2)``.

    How much labelling effort a proxy of correlation ``rho`` is worth. Returns ``1.0``
    (no gain) for an undefined correlation, and saturates at ``|rho| -> 1`` rather than
    dividing by zero — a perfect proxy would need no labels at all, which is never the
    regime we are in.
    """
    if rho is None:
        return 1.0
    denom = 1.0 - rho * rho
    if denom <= _MIN_VARIANCE_DENOM:
        return 1.0 / _MIN_VARIANCE_DENOM
    return 1.0 / denom


# --- prediction-powered inference (PPI++) ------------------------------------
@dataclass(frozen=True)
class PPIConfig:
    """Tunables for the prediction-powered interval. No literal appears at a call site."""

    z: float = 1.96  # normal-approximation quantile (95% by default)
    lambda_min: float = 0.0  # clamp floor; 0 => classical labelled-only estimator
    lambda_max: float = 1.0  # clamp ceiling; 1 => vanilla (untuned) PPI
    min_labeled: int = 2  # below this a sample variance does not exist

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


@dataclass(frozen=True)
class PPIEstimate:
    """A prediction-powered mean estimate and its interval.

    ``classical_lo``/``classical_hi`` are the *same-family* (lambda = 0) interval on the
    labelled data alone. Comparing against those isolates the gain actually attributable
    to the proxy; comparing a normal-approximation PPI interval directly against a Wilson
    score interval would also fold in the interval-type difference, which at small ``n``
    is the larger effect and is not a gain at all.
    """

    point: float
    lo: float
    hi: float
    lam: float
    n_labeled: int
    n_unlabeled: int
    classical_lo: float
    classical_hi: float
    degenerate: str | None = None

    @property
    def half_width(self) -> float:
        return (self.hi - self.lo) / 2.0

    @property
    def classical_half_width(self) -> float:
        return (self.classical_hi - self.classical_lo) / 2.0

    @property
    def variance_reduction(self) -> float:
        """Fraction of the classical variance removed by the proxy, in ``[0, 1)``."""
        c = self.classical_half_width
        if c <= 0.0:
            return 0.0
        ratio = self.half_width / c
        return max(0.0, 1.0 - ratio * ratio)


def ppi_plus_interval(
    labeled: Sequence[tuple[float, int]],
    unlabeled_proxy: Sequence[float],
    cfg: PPIConfig | None = None,
) -> PPIEstimate:
    """Power-tuned prediction-powered interval for a mean outcome rate.

    ``labeled`` pairs each authoritative outcome with the proxy's value for the same
    unit; ``unlabeled_proxy`` holds proxy values for units with no authoritative label.
    The estimator is ``theta = mean_L(Y) + lambda * (mean_U(f) - mean_L(f))`` with
    ``lambda`` chosen to minimise variance, so ``lambda = 0`` recovers the classical
    estimator exactly and the tuned form is asymptotically never worse (PPI++).

    Fail-closed by construction: whenever the normal approximation cannot be trusted —
    too few labels, a single outcome class (zero labelled variance, which would collapse
    the interval to a false-certainty point), a constant proxy, or no unlabeled data —
    the returned interval is the **Wilson** interval on the labelled outcomes and
    ``degenerate`` says why. An interval we cannot trust must never read as the tightest.
    """
    cfg = cfg or PPIConfig()
    n = len(labeled)
    outcomes = [o for _, o in labeled]
    for o in outcomes:
        if o not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {o}")
    k = sum(outcomes)
    fallback_lo, fallback_hi = wilson_interval(k, n, cfg.z)
    point_fallback = (k / n) if n else 0.0

    def _degenerate(reason: str) -> PPIEstimate:
        logger.warning(
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
    ys = [float(o) for o in outcomes]
    var_f_l = _variance(proxies)
    if var_f_l <= 0.0:
        return _degenerate(f"constant proxy: value == {proxies[0]:.4g} for all {n} records")
    if not math.isfinite(var_f_l):
        return _degenerate("proxy variance is not representable as a float")

    var_y = _variance(ys)
    cov_yf = _covariance(proxies, ys)
    # lambda* = cov / (var_f * (1 + n/N)); the (1 + n/N) factor charges for the noise in
    # the unlabeled mean, so a small unlabeled pool tunes conservatively toward classical.
    lam = cov_yf / (var_f_l * (1.0 + n / big_n))
    lam = max(cfg.lambda_min, min(cfg.lambda_max, lam))

    var_u_f = _variance(unlabeled_proxy) if big_n >= 2 else 0.0
    point = _mean(ys) + lam * (_mean(unlabeled_proxy) - _mean(proxies))
    var_resid = var_y - 2.0 * lam * cov_yf + lam * lam * var_f_l
    var_point = max(0.0, var_resid) / n + (lam * lam) * var_u_f / big_n
    se = math.sqrt(var_point)
    # lambda = 0 baseline in the same (normal-approximation) family, for honest attribution.
    se_classical = math.sqrt(var_y / n)

    def _clip(lo: float, hi: float) -> tuple[float, float]:
        return max(0.0, lo), min(1.0, hi)

    lo, hi = _clip(point - cfg.z * se, point + cfg.z * se)
    c_lo, c_hi = _clip(_mean(ys) - cfg.z * se_classical, _mean(ys) + cfg.z * se_classical)
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
        point=max(0.0, min(1.0, point)),
        lo=lo,
        hi=hi,
        lam=lam,
        n_labeled=n,
        n_unlabeled=big_n,
        classical_lo=c_lo,
        classical_hi=c_hi,
    )


# --- recalibration -----------------------------------------------------------
@runtime_checkable
class Calibrator(Protocol):
    def fit(self, probs: Sequence[float], outcomes: Sequence[int]) -> Calibrator: ...
    def predict(self, prob: float) -> float: ...


class IsotonicCalibrator:
    """Monotonic recalibration via Pool Adjacent Violators. Dependency-free."""

    def __init__(self) -> None:
        self._x: list[float] = []
        self._y: list[float] = []
        self._fitted = False

    def fit(self, probs: Sequence[float], outcomes: Sequence[int]) -> IsotonicCalibrator:
        _check_pairs(probs, outcomes)
        order = sorted(range(len(probs)), key=lambda i: probs[i])
        xs = [probs[i] for i in order]
        ys = [float(outcomes[i]) for i in order]
        # Pre-aggregate identical probabilities to remove input-order sensitivity.
        # Ties at the same x become a single weighted block before PAV runs.
        xs_u: list[float] = []
        ys_u: list[float] = []
        ws_u: list[float] = []
        i = 0
        while i < len(xs):
            j = i
            while j < len(xs) and xs[j] == xs[i]:
                j += 1
            n = j - i
            xs_u.append(xs[i])
            ys_u.append(sum(ys[i:j]) / n)
            ws_u.append(float(n))
            i = j
        # PAV: blocks of (weighted average, weight, constituent xs); merge while non-monotonic.
        # Track all xs per block so that every original training point is retained in _x.
        values: list[float] = []
        weights: list[float] = []
        block_xs: list[list[float]] = []
        for x, y, w in zip(xs_u, ys_u, ws_u, strict=True):
            values.append(y)
            weights.append(w)
            block_xs.append([x])
            while len(values) > 1 and values[-2] > values[-1]:
                v2, w2, bx2 = values.pop(), weights.pop(), block_xs.pop()
                v1, w1, bx1 = values.pop(), weights.pop(), block_xs.pop()
                merged_w = w1 + w2
                values.append((v1 * w1 + v2 * w2) / merged_w)
                weights.append(merged_w)
                block_xs.append(bx1 + bx2)  # sorted left→right (bx1 < bx2 by construction)
        # Expand each block back to its original xs, all with the block's calibrated value.
        # Within a block y0==y1, so linear interpolation returns the constant; between blocks
        # it interpolates smoothly across the block boundary.
        self._x = [x for bx in block_xs for x in bx]
        self._y = [v for v, bx in zip(values, block_xs, strict=True) for _ in bx]
        self._fitted = True
        return self

    def predict(self, prob: float) -> float:
        if not self._fitted:
            raise RuntimeError("IsotonicCalibrator.predict before fit")
        if prob <= self._x[0]:
            return self._y[0]
        if prob >= self._x[-1]:
            return self._y[-1]
        # piecewise-linear interpolation between knots
        for i in range(1, len(self._x)):
            if prob <= self._x[i]:
                x0, x1 = self._x[i - 1], self._x[i]
                y0, y1 = self._y[i - 1], self._y[i]
                if x1 == x0:
                    return y1
                t = (prob - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        return self._y[-1]


# --- aggregate report --------------------------------------------------------
@dataclass(frozen=True)
class CalibrationReport:
    ece: float
    mce: float
    brier: float
    auroc: float | None
    passes: bool
    # Why discrimination could not be measured (constant predictor / single outcome class /
    # too few samples), or ``None`` when the slice supports a meaningful verdict. Mirrors
    # ``calibration_report.SliceReport.degenerate`` so both report paths say the same thing.
    # Defaulted so existing keyword construction and unpacking keep working.
    degenerate: str | None = None


def _shape_degeneracy(probs: Sequence[float], outcomes: Sequence[int], roc: float | None) -> str:
    """Describe why this slice's *shape* cannot evidence discrimination (``""`` if it can).

    Constant predictors are named ahead of single-class outcomes because when a slice is
    both, the constant score is the root cause: it cannot rank anything, whatever the
    labels do. Mirrors the ordering in ``calibration_report.analyze_slice``.
    """
    n = len(probs)
    if len(set(probs)) == 1:
        return f"constant predictor: probability == {probs[0]:.4g} for all {n} records"
    if roc is None:
        cls = "correct" if outcomes and outcomes[0] == 1 else "incorrect"
        return f"single outcome class: all {n} outcomes are {cls}"
    return ""


def evaluate_calibration(
    probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int,
    ece_target: float,
    mce_target: float,
    auroc_target: float,
    min_samples: int = 1,
    require_discrimination: bool = False,
) -> CalibrationReport:
    """Score a slice against the ship-gate targets.

    Calibration alone is a vanity metric: a forecaster that is confidently wrong every
    time is perfectly "calibrated" against its own base rate. ``auroc_target`` is the
    resolution check that catches that — but AUROC is undefined when the slice has one
    outcome class or a constant predictor, and an undefined check cannot reject anything.

    ``degenerate`` therefore always reports such a slice (and logs it at WARNING), while
    two independent, opt-in guards decide whether it also *fails*:

    * ``min_samples`` — floor on slice size. An explicit floor is a rejection in its own
      right, so it fails the gate whenever it trips; the default of 1 can never trip
      (``_check_pairs`` already rejects empty input).
    * ``require_discrimination`` — when True, a slice whose *shape* precludes measuring
      discrimination (constant predictor, single outcome class) cannot pass. Left False
      by default so existing gates keep their semantics until they opt in: an all-correct
      golden set is a legitimate, desired shape, not a failure.

    Both default to the pre-guard behaviour, so callers that pass neither are unaffected.
    """
    if min_samples < 1:
        raise ValueError(f"min_samples must be >= 1, got {min_samples}")
    # Bin once and derive ECE/MCE from the shared bins (avoids re-binning 2-3x).
    bins = reliability_bins(probs, outcomes, n_bins)
    total = len(probs)
    ece = sum((b.count / total) * abs(b.accuracy - b.mean_conf) for b in bins if b.is_populated)
    gaps = [abs(b.accuracy - b.mean_conf) for b in bins if b.is_populated]
    mce = max(gaps) if gaps else 0.0
    brier = brier_score(probs, outcomes)
    try:
        roc = auroc(list(probs), list(outcomes))
    except ValueError:
        roc = None  # single-class slice: discrimination undefined

    undersized = len(probs) < min_samples
    shape_reason = _shape_degeneracy(probs, outcomes, roc)
    # Size before shape: when a slice is both undersized and misshapen, too little data is
    # the root cause and the caller should hear that first.
    degenerate = (
        f"insufficient samples: n={len(probs)} < min_samples={min_samples}"
        if undersized
        else (shape_reason or None)
    )
    if degenerate is not None:
        enforced = undersized or (require_discrimination and bool(shape_reason))
        logger.warning(
            "calibration slice cannot evidence discrimination (%s); this slice %s the gate "
            "on that criterion (min_samples=%d, require_discrimination=%s)",
            degenerate,
            "fails" if enforced else "is not judged by",
            min_samples,
            require_discrimination,
        )

    passes = (
        ece <= ece_target
        and mce <= mce_target
        and (roc is None or roc >= auroc_target)
        and not undersized
        and not (require_discrimination and bool(shape_reason))
    )
    return CalibrationReport(
        ece=ece, mce=mce, brier=brier, auroc=roc, passes=passes, degenerate=degenerate
    )
