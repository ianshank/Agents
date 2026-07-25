import math
import random
from itertools import pairwise

import pytest

from agent_core import (
    IsotonicCalibrator,
    PPIConfig,
    auroc,
    brier_decomposition,
    brier_score,
    effective_n_multiplier,
    evaluate_calibration,
    expected_calibration_error,
    maximum_calibration_error,
    pearson_r,
    ppi_plus_interval,
    reliability_bins,
    selective_risk_coverage,
    wilson_interval,
)


def test_ece_hand_value():
    # group @0.9: 7/10 correct (gap .2); group @0.6: 6/10 correct (gap 0)
    probs = [0.9] * 10 + [0.6] * 10
    outcomes = [1] * 7 + [0] * 3 + [1] * 6 + [0] * 4
    assert math.isclose(expected_calibration_error(probs, outcomes, n_bins=10), 0.1, abs_tol=1e-9)
    assert math.isclose(maximum_calibration_error(probs, outcomes, n_bins=10), 0.2, abs_tol=1e-9)


def test_perfect_calibration_is_zero_ece():
    probs = [0.2] * 10 + [0.8] * 10
    outcomes = [1] * 2 + [0] * 8 + [1] * 8 + [0] * 2
    assert expected_calibration_error(probs, outcomes, n_bins=10) < 1e-12


def test_brier_hand_value():
    assert math.isclose(brier_score([0.2, 0.8], [0, 1]), 0.04, abs_tol=1e-12)


def test_brier_murphy_decomposition_identity():
    # distinct prob per bin -> decomposition reconstructs Brier exactly
    probs = [0.1] * 10 + [0.5] * 10 + [0.9] * 10
    outcomes = [1] * 1 + [0] * 9 + [1] * 5 + [0] * 5 + [1] * 9 + [0] * 1
    decomp = brier_decomposition(probs, outcomes, n_bins=10)
    assert math.isclose(decomp.reconstructed, brier_score(probs, outcomes), abs_tol=1e-9)


@pytest.mark.parametrize(
    "labels,expected",
    [
        ([1, 1, 0, 0], 1.0),
        ([0, 0, 1, 1], 0.0),
        ([1, 0, 1, 0], 0.75),
    ],
)
def test_auroc_known_orderings(labels, expected):
    scores = [0.9, 0.8, 0.7, 0.6]
    assert math.isclose(auroc(scores, labels), expected, abs_tol=1e-12)


def test_auroc_requires_both_classes():
    with pytest.raises(ValueError):
        auroc([0.1, 0.2], [1, 1])


def test_auroc_rejects_non_binary_labels():
    with pytest.raises(ValueError, match="binary"):
        auroc([0.9, 0.5, 0.1], [1, 2, 0])


def test_wilson_interval_contains_point_and_bounded():
    lo, hi = wilson_interval(7, 10, z=1.96)
    assert 0.0 <= lo < 0.7 < hi <= 1.0


def test_reliability_bins_handle_p_equals_one():
    bins = reliability_bins([1.0, 1.0, 0.95], [1, 0, 1], n_bins=10)
    last = bins[-1]
    assert last.count == 3  # p==1.0 captured in closed last bin


def test_isotonic_reduces_ece_and_is_monotonic():
    # systematically overconfident: predicted = actual_acc + 0.2
    probs, outcomes = [], []
    for pred, acc in [(0.6, 0.4), (0.7, 0.5), (0.8, 0.6), (0.9, 0.7)]:
        n_correct = round(acc * 10)
        probs += [pred] * 10
        outcomes += [1] * n_correct + [0] * (10 - n_correct)

    raw_ece = expected_calibration_error(probs, outcomes, n_bins=10)
    cal = IsotonicCalibrator().fit(probs, outcomes)
    recal = [cal.predict(p) for p in probs]
    recal_ece = expected_calibration_error(recal, outcomes, n_bins=10)
    assert recal_ece < raw_ece

    # monotonic non-decreasing mapping
    grid = [i / 20 for i in range(21)]
    mapped = [cal.predict(x) for x in grid]
    assert all(b >= a - 1e-12 for a, b in pairwise(mapped))


def test_isotonic_fit_handles_duplicate_probabilities() -> None:
    # Duplicate x values must be pre-aggregated before PAV so the result is
    # input-order-independent (e.g. two samples at p=0.8 with different outcomes
    # must yield the same calibrated output regardless of order).
    probs = [0.8, 0.8, 0.9, 0.9]
    outcomes_ab = [1, 0, 1, 0]
    outcomes_ba = [0, 1, 0, 1]  # same pairs, reversed within each tie group
    cal_ab = IsotonicCalibrator().fit(probs, outcomes_ab)
    cal_ba = IsotonicCalibrator().fit(probs, outcomes_ba)
    assert cal_ab.predict(0.8) == cal_ba.predict(0.8)
    assert cal_ab.predict(0.9) == cal_ba.predict(0.9)
    # Both should average to 0.5 (1 hit / 2 samples each x)
    assert math.isclose(cal_ab.predict(0.8), 0.5, abs_tol=1e-12)
    assert math.isclose(cal_ab.predict(0.9), 0.5, abs_tol=1e-12)


def test_selective_coverage_is_monotonic():
    probs = [0.95, 0.9, 0.6, 0.55, 0.4]
    outcomes = [1, 1, 0, 1, 0]
    pts = selective_risk_coverage(probs, outcomes)
    coverages = [c for c, _ in pts]
    assert all(b >= a for a, b in pairwise(coverages))


def test_selective_coverage_stable_under_tied_probabilities() -> None:
    """Tied probabilities must be committed as a single threshold step.

    The (coverage, risk) curve must be identical regardless of the order in which
    tied items appear in the input — previously one point was appended per sample,
    making the result input-order-sensitive.
    """
    probs_fwd = [0.9, 0.8, 0.8, 0.5]
    outcomes_fwd = [1, 1, 0, 0]
    probs_rev = [0.9, 0.8, 0.8, 0.5]
    outcomes_rev = [1, 0, 1, 0]  # tied pair swapped
    pts_fwd = selective_risk_coverage(probs_fwd, outcomes_fwd)
    pts_rev = selective_risk_coverage(probs_rev, outcomes_rev)
    assert pts_fwd == pts_rev, "curve must be invariant under permutation of tied inputs"
    assert len(pts_fwd) == 3  # one point per unique threshold: 0.9, 0.8, 0.5


def test_ship_gate_rejects_calibrated_but_undiscriminating_model():
    # base-rate forecaster: perfectly calibrated (ECE 0) but AUROC 0.5 -> must FAIL
    probs = [0.5] * 10
    outcomes = [1] * 5 + [0] * 5
    report = evaluate_calibration(
        probs, outcomes, n_bins=10, ece_target=0.05, mce_target=0.12, auroc_target=0.80
    )
    assert report.ece < 1e-9
    assert report.auroc is not None
    assert math.isclose(report.auroc, 0.5, abs_tol=1e-9)
    assert report.passes is False  # the vanity-metric guard in action
    # A constant score cannot rank anything, so the slice is also reported as degenerate —
    # here AUROC is still defined (both classes present) and rejects it on its own.
    assert report.degenerate is not None
    assert "constant predictor" in report.degenerate


def _gate(
    probs: list[float],
    outcomes: list[int],
    *,
    min_samples: int = 1,
    require_discrimination: bool = False,
):
    """Score a slice against fixed ship-gate targets, varying only the guards."""
    return evaluate_calibration(
        probs,
        outcomes,
        n_bins=10,
        ece_target=0.05,
        mce_target=0.12,
        auroc_target=0.80,
        min_samples=min_samples,
        require_discrimination=require_discrimination,
    )


# (label, probs, outcomes, expected substring in `degenerate`). The single-class cases vary
# the probabilities so the slice is *only* single-class, not also a constant predictor.
_DEGENERATE_SLICES = [
    ("all-correct", [0.5, 0.6, 0.7, 0.8, 0.9, 0.95], [1] * 6, "single outcome class"),
    ("all-incorrect", [0.5, 0.6, 0.7, 0.8, 0.9, 0.95], [0] * 6, "single outcome class"),
    ("constant-predictor", [0.7] * 12, [1] * 6 + [0] * 6, "constant predictor"),
]


@pytest.mark.parametrize(
    ("label", "probs", "outcomes", "expected"),
    _DEGENERATE_SLICES,
    ids=[case[0] for case in _DEGENERATE_SLICES],
)
def test_degeneracy_is_reported_without_changing_the_default_verdict(
    label: str, probs: list[float], outcomes: list[int], expected: str
) -> None:
    """Degeneracy is always *named*; by default it does not change `passes`.

    Reporting is unconditional so an operator can see that a green verdict rests on a
    slice with no discrimination evidence. Enforcement stays opt-in (next test) because
    an all-correct golden set is a legitimate, desired shape.
    """
    report = _gate(probs, outcomes)
    assert report.degenerate is not None
    assert expected in report.degenerate


def test_require_discrimination_rejects_slices_that_cannot_evidence_it() -> None:
    """The bug this guard closes: a forecaster wrong 100% of the time used to pass.

    All-incorrect at confidence 0.0 is 'perfectly calibrated' against its own base rate
    (ECE 0) and has an undefined AUROC, so every criterion was vacuously satisfied.
    """
    probs, outcomes = [0.0] * 12, [0] * 12
    lenient = _gate(probs, outcomes)
    assert lenient.ece < 1e-9 and lenient.auroc is None
    assert lenient.passes is True  # documents the historical (default) behaviour

    strict = _gate(probs, outcomes, require_discrimination=True)
    assert strict.passes is False
    assert strict.degenerate is not None


def test_min_samples_floor_rejects_undersized_slices() -> None:
    """An explicit floor rejects on its own -- it does not need the discrimination flag."""
    report = _gate([1.0], [1], min_samples=12)
    assert report.passes is False
    assert report.degenerate == "insufficient samples: n=1 < min_samples=12"


def test_min_samples_reports_size_before_shape() -> None:
    """A slice that is both undersized and constant names the sample floor first."""
    report = _gate([0.5] * 3, [1, 0, 1], min_samples=12)
    assert report.degenerate is not None
    assert report.degenerate.startswith("insufficient samples")


def test_guards_default_to_pre_guard_behaviour() -> None:
    """A healthy slice is scored identically with guards implicit or explicitly off."""
    probs = [0.9] * 10 + [0.2] * 10
    outcomes = [1] * 9 + [0] + [1] * 2 + [0] * 8
    # Called the pre-guard way: no guard arguments at all.
    implicit = evaluate_calibration(
        probs, outcomes, n_bins=10, ece_target=0.05, mce_target=0.12, auroc_target=0.80
    )
    explicit = _gate(probs, outcomes, min_samples=1, require_discrimination=False)
    assert implicit == explicit


def test_require_discrimination_does_not_rescue_a_failing_slice() -> None:
    """The guard only ever removes a pass; it never turns a fail into a pass."""
    probs = [0.99] * 10  # badly over-confident against a 50% base rate
    outcomes = [1] * 5 + [0] * 5
    assert _gate(probs, outcomes).passes is False
    assert _gate(probs, outcomes, require_discrimination=True).passes is False


def test_invalid_min_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="min_samples must be >= 1"):
        _gate([1.0], [1], min_samples=0)


def test_degeneracy_is_logged_for_operator_visibility(caplog) -> None:
    with caplog.at_level("WARNING", logger="agent_core.calibration"):
        _gate([1.0] * 12, [1] * 12)
    assert any("cannot evidence discrimination" in r.message for r in caplog.records)


# --- pearson_r / effective_n_multiplier --------------------------------------
def _r(xs: list[float], ys: list[float]) -> float:
    """pearson_r, asserted defined — keeps the numeric cases free of None-handling noise."""
    value = pearson_r(xs, ys)
    assert value is not None
    return value


def test_pearson_r_known_values() -> None:
    assert math.isclose(_r([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0, abs_tol=1e-12)
    assert math.isclose(_r([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]), -1.0, abs_tol=1e-12)
    assert math.isclose(_r([1.0, 2.0, 3.0, 4.0], [1.0, 3.0, 2.0, 4.0]), 0.8, abs_tol=1e-12)


@pytest.mark.parametrize(
    ("xs", "ys", "why"),
    [
        ([1.0, 1.0, 1.0], [0.0, 1.0, 0.0], "constant x"),
        ([0.0, 1.0, 0.0], [2.0, 2.0, 2.0], "constant y"),
        ([1.0], [1.0], "single point"),
    ],
    ids=["constant-x", "constant-y", "n-1"],
)
def test_pearson_r_is_none_when_undefined(xs, ys, why) -> None:
    """Undefined is not zero: reporting 0.0 would claim evidence of no relationship."""
    assert pearson_r(xs, ys) is None, why


def test_pearson_r_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="equal length"):
        pearson_r([1.0, 2.0], [1.0])


def test_pearson_r_survives_underflowing_variances() -> None:
    """Regression (found by the property suite): tiny variances must not divide by zero.

    Both variances here are positive but so small that their *product* underflows to
    exactly 0.0, so the old ``sqrt(vx * vy)`` denominator raised ZeroDivisionError.
    Rooting each variance first keeps the factors representable.
    """
    tiny = [0.0, 3.2900281484057283e-83]
    assert math.isclose(_r(tiny, tiny), 1.0, abs_tol=1e-9)


def test_pearson_r_handles_huge_values_without_overflow() -> None:
    huge = [-1e308, 1e308]
    result = pearson_r(huge, huge)
    assert result is None or -1.0 <= result <= 1.0


def test_effective_n_multiplier_matches_the_closed_form() -> None:
    assert math.isclose(effective_n_multiplier(0.0), 1.0, abs_tol=1e-12)
    assert math.isclose(effective_n_multiplier(0.5), 1 / 0.75, abs_tol=1e-12)
    assert math.isclose(effective_n_multiplier(-0.5), 1 / 0.75, abs_tol=1e-12)  # sign-free


def test_effective_n_multiplier_saturates_and_never_divides_by_zero() -> None:
    assert effective_n_multiplier(None) == 1.0  # undefined correlation buys nothing
    assert math.isfinite(effective_n_multiplier(1.0))
    assert math.isfinite(effective_n_multiplier(-1.0))


# --- prediction-powered inference (PPI++) ------------------------------------
def _synthetic(n: int, big_n: int, signal: float, seed: int = 0):
    """Labelled pairs + an unlabeled proxy pool whose correlation tracks ``signal``."""
    rng = random.Random(seed)
    labeled = []
    for _ in range(n):
        y = 1 if rng.random() < 0.7 else 0
        labeled.append((signal * y + (1 - signal) * rng.random(), y))
    unlabeled = []
    for _ in range(big_n):
        y = 1 if rng.random() < 0.7 else 0
        unlabeled.append(signal * y + (1 - signal) * rng.random())
    return labeled, unlabeled


def test_ppi_config_defaults() -> None:
    cfg = PPIConfig()
    assert (cfg.z, cfg.lambda_min, cfg.lambda_max, cfg.min_labeled) == (1.96, 0.0, 1.0, 2)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PPIConfig(z=0.0),
        lambda: PPIConfig(z=float("nan")),
        lambda: PPIConfig(z=float("inf")),
        lambda: PPIConfig(lambda_min=0.9, lambda_max=0.1),
        lambda: PPIConfig(lambda_min=float("nan")),
        lambda: PPIConfig(min_labeled=1),
    ],
)
def test_ppi_config_rejects_invalid_values(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_ppi_rejects_non_binary_outcomes() -> None:
    with pytest.raises(ValueError, match="outcome must be 0 or 1"):
        ppi_plus_interval([(0.5, 2)], [0.5])


def test_ppi_uninformative_proxy_collapses_to_the_classical_estimator() -> None:
    """lambda -> 0 is the whole safety argument: PPI++ can never be worse than classical."""
    labeled, unlabeled = _synthetic(200, 4000, signal=0.0, seed=11)
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is None
    assert math.isclose(est.lam, 0.0, abs_tol=1e-9)
    assert math.isclose(est.half_width, est.classical_half_width, abs_tol=1e-12)
    assert math.isclose(est.variance_reduction, 0.0, abs_tol=1e-9)


def test_ppi_informative_proxy_is_strictly_narrower() -> None:
    labeled, unlabeled = _synthetic(200, 4000, signal=0.9, seed=3)
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is None
    assert est.lam > 0.0
    assert est.half_width < est.classical_half_width
    assert est.variance_reduction > 0.0


def test_ppi_variance_reduction_tracks_rho_squared() -> None:
    """The reported gain must match the theory it is sold on: 1 - Var ratio ~= rho^2."""
    labeled, unlabeled = _synthetic(400, 8000, signal=0.7, seed=5)
    est = ppi_plus_interval(labeled, unlabeled)
    rho = _r([f for f, _ in labeled], [float(o) for _, o in labeled])
    assert abs(est.variance_reduction - rho * rho) < 0.1


def test_ppi_single_outcome_class_falls_back_to_wilson_not_a_point() -> None:
    """The dangerous case: zero labelled variance makes the Wald SE zero.

    A naive normal-approximation interval collapses to [1, 1] — maximal confidence from
    20 observations — which is exactly the false certainty this gate must never emit.
    """
    labeled = [(0.9, 1)] * 20
    est = ppi_plus_interval(labeled, [0.9] * 500)
    assert est.degenerate is not None and "single outcome class" in est.degenerate
    assert (est.lo, est.hi) != (1.0, 1.0)
    assert math.isclose(est.lo, wilson_interval(20, 20)[0], abs_tol=1e-12)
    assert math.isclose(est.hi, wilson_interval(20, 20)[1], abs_tol=1e-12)


@pytest.mark.parametrize(
    ("labeled", "unlabeled", "expected"),
    [
        ([(0.5, 1)], [0.5] * 10, "insufficient labelled samples"),
        ([(0.5, 1), (0.6, 0)], [], "no unlabeled proxy values"),
        ([(0.5, 1), (0.5, 0), (0.5, 1)], [0.5] * 10, "constant proxy"),
    ],
    ids=["too-few-labels", "no-unlabeled", "constant-proxy"],
)
def test_ppi_degenerate_paths_fall_back_to_wilson(labeled, unlabeled, expected) -> None:
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is not None and expected in est.degenerate
    assert est.lam == 0.0
    k = sum(o for _, o in labeled)
    assert math.isclose(est.lo, wilson_interval(k, len(labeled))[0], abs_tol=1e-12)


def test_ppi_degeneracy_is_logged_for_operator_visibility(caplog) -> None:
    with caplog.at_level("WARNING", logger="agent_core.calibration"):
        est = ppi_plus_interval([(0.9, 1)] * 8, [0.9] * 50)
    assert est.degenerate is not None
    assert any("falling back to the Wilson interval" in r.message for r in caplog.records)


def test_ppi_single_unlabeled_value_is_handled() -> None:
    """N == 1 has no variance estimate; the code must not divide by (N-1) == 0."""
    labeled, _ = _synthetic(30, 0, signal=0.6, seed=2)
    est = ppi_plus_interval(labeled, [0.5])
    assert math.isfinite(est.lo) and math.isfinite(est.hi)
    assert 0.0 <= est.lo <= est.hi <= 1.0


def test_ppi_lambda_clamp_is_configurable() -> None:
    """Pinning lambda to 0 must reproduce the classical estimator exactly."""
    labeled, unlabeled = _synthetic(150, 3000, signal=0.9, seed=9)
    pinned = ppi_plus_interval(labeled, unlabeled, PPIConfig(lambda_max=0.0))
    assert pinned.lam == 0.0
    assert math.isclose(pinned.half_width, pinned.classical_half_width, abs_tol=1e-12)


def test_ppi_interval_is_always_a_valid_probability_interval() -> None:
    for signal in (0.0, 0.3, 0.6, 0.95):
        for n, big_n in ((10, 100), (50, 1000), (200, 5000)):
            est = ppi_plus_interval(*_synthetic(n, big_n, signal, seed=n + int(signal * 100)))
            assert 0.0 <= est.lo <= est.point <= est.hi <= 1.0
