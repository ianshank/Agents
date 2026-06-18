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
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple, runtime_checkable



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


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
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
) -> List[Bin]:
    _check_pairs(probs, outcomes)
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    edges = [i / n_bins for i in range(n_bins + 1)]
    bins: List[Bin] = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        # last bin is closed on the right to capture p == 1.0
        if b == n_bins - 1:
            members = [(p, o) for p, o in zip(probs, outcomes) if lo <= p <= hi]
        else:
            members = [(p, o) for p, o in zip(probs, outcomes) if lo <= p < hi]
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
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


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
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
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
    rank_sum_pos = sum(r for r, y in zip(ranks, labels) if y == 1)
    n_pos, n_neg = len(pos), len(neg)
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return u / (n_pos * n_neg)


# --- selective prediction (abstention) --------------------------------------
def selective_risk_coverage(
    probs: Sequence[float], outcomes: Sequence[int]
) -> List[Tuple[float, float]]:
    """Return (coverage, risk) points as the commit threshold sweeps high->low.

    coverage = fraction committed; risk = error rate among committed. Coverage is
    non-decreasing as the threshold drops.
    """
    _check_pairs(probs, outcomes)
    n = len(probs)
    order = sorted(range(n), key=lambda i: probs[i], reverse=True)
    committed = 0
    errors = 0
    points: List[Tuple[float, float]] = []
    for idx in order:
        committed += 1
        # treat a commit as predicting "true"; error if outcome is 0
        if outcomes[idx] == 0:
            errors += 1
        coverage = committed / n
        risk = errors / committed
        points.append((coverage, risk))
    return points


# --- recalibration -----------------------------------------------------------
@runtime_checkable
class Calibrator(Protocol):
    def fit(self, probs: Sequence[float], outcomes: Sequence[int]) -> "Calibrator": ...
    def predict(self, prob: float) -> float: ...


class IsotonicCalibrator:
    """Monotonic recalibration via Pool Adjacent Violators. Dependency-free."""

    def __init__(self) -> None:
        self._x: List[float] = []
        self._y: List[float] = []
        self._fitted = False

    def fit(self, probs: Sequence[float], outcomes: Sequence[int]) -> "IsotonicCalibrator":
        _check_pairs(probs, outcomes)
        order = sorted(range(len(probs)), key=lambda i: probs[i])
        xs = [probs[i] for i in order]
        ys = [float(outcomes[i]) for i in order]
        # PAV: blocks of (sum, weight); merge while non-monotonic
        values: List[float] = []
        weights: List[float] = []
        knots: List[float] = []
        for x, y in zip(xs, ys):
            values.append(y)
            weights.append(1.0)
            knots.append(x)
            while len(values) > 1 and values[-2] > values[-1]:
                v2, w2 = values.pop(), weights.pop()
                v1, w1 = values.pop(), weights.pop()
                merged_w = w1 + w2
                values.append((v1 * w1 + v2 * w2) / merged_w)
                weights.append(merged_w)
                knots.pop()  # keep the left-most knot of the merged block
        # After PAV, `knots`/`values` align 1:1 with blocks (left-most x retained).
        self._x = list(knots)
        self._y = list(values)
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
    auroc: Optional[float]
    passes: bool


def evaluate_calibration(
    probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    n_bins: int,
    ece_target: float,
    mce_target: float,
    auroc_target: float,
) -> CalibrationReport:
    # Bin once and derive ECE/MCE from the shared bins (avoids re-binning 2-3x).
    bins = reliability_bins(probs, outcomes, n_bins)
    total = len(probs)
    ece = sum(
        (b.count / total) * abs(b.accuracy - b.mean_conf)
        for b in bins
        if b.is_populated
    )
    gaps = [abs(b.accuracy - b.mean_conf) for b in bins if b.is_populated]
    mce = max(gaps) if gaps else 0.0
    brier = brier_score(probs, outcomes)
    try:
        roc = auroc(list(probs), list(outcomes))
    except ValueError:
        roc = None  # single-class slice: discrimination undefined
    passes = (
        ece <= ece_target
        and mce <= mce_target
        and (roc is None or roc >= auroc_target)
    )
    return CalibrationReport(ece=ece, mce=mce, brier=brier, auroc=roc, passes=passes)
