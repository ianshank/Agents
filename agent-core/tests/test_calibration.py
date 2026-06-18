import math
from itertools import pairwise

import pytest

from agent_core import (
    IsotonicCalibrator,
    auroc,
    brier_decomposition,
    brier_score,
    evaluate_calibration,
    expected_calibration_error,
    maximum_calibration_error,
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


def test_auroc_rejects_non_binary_labels() -> None:
    with pytest.raises(ValueError, match="binary labels"):
        auroc([0.5, 0.6, 0.7], [0, 1, 2])


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
    """Duplicate training probabilities must be averaged into one knot, not kept separate."""
    import math

    cal = IsotonicCalibrator().fit([0.5, 0.5, 0.5], [0, 1, 0])
    # three 0.5-prob samples: 0+1+0 → average = 1/3
    assert math.isclose(cal.predict(0.5), 1 / 3, abs_tol=1e-12)
    # predict() must still be monotonic
    grid = [i / 20 for i in range(21)]
    mapped = [cal.predict(x) for x in grid]
    assert all(b >= a - 1e-12 for a, b in pairwise(mapped))


def test_selective_coverage_is_monotonic():
    probs = [0.95, 0.9, 0.6, 0.55, 0.4]
    outcomes = [1, 1, 0, 1, 0]
    pts = selective_risk_coverage(probs, outcomes)
    coverages = [c for c, _ in pts]
    assert all(b >= a for a, b in pairwise(coverages))


def test_ship_gate_rejects_calibrated_but_undiscriminating_model():
    # base-rate forecaster: perfectly calibrated (ECE 0) but AUROC 0.5 -> must FAIL
    probs = [0.5] * 10
    outcomes = [1] * 5 + [0] * 5
    report = evaluate_calibration(
        probs, outcomes, n_bins=10, ece_target=0.05, mce_target=0.12, auroc_target=0.80
    )
    assert report.ece < 1e-9
    assert math.isclose(report.auroc, 0.5, abs_tol=1e-9)
    assert report.passes is False  # the vanity-metric guard in action
