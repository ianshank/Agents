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
