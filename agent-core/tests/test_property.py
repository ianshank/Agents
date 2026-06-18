"""Property-based tests.

Example tests catch the bugs you thought of; these catch the ones you didn't.
Invariants asserted over randomised inputs: metric ranges, and isotonic
monotonicity evaluated at *non-knot* points (the gap the review flagged).
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_core import (
    IsotonicCalibrator,
    auroc,
    brier_score,
    expected_calibration_error,
    maximum_calibration_error,
)

probs_st = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=200)


def _outcomes(n, data):
    return [data.draw(st.integers(0, 1)) for _ in range(n)]


@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=1, max_size=200,
    )
)
def test_ece_and_mce_in_unit_interval(pairs):
    probs = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]
    ece = expected_calibration_error(probs, outcomes, n_bins=10)
    mce = maximum_calibration_error(probs, outcomes, n_bins=10)
    assert 0.0 <= ece <= 1.0
    assert 0.0 <= mce <= 1.0


@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=1, max_size=200,
    )
)
def test_brier_in_unit_interval(pairs):
    probs = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]
    assert 0.0 <= brier_score(probs, outcomes) <= 1.0


@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=2, max_size=200,
    )
)
def test_auroc_in_unit_interval_when_both_classes_present(pairs):
    probs = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]
    if 0 in outcomes and 1 in outcomes:
        assert 0.0 <= auroc(probs, outcomes) <= 1.0


@settings(max_examples=200)
@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=2, max_size=200,
    )
)
def test_isotonic_monotone_at_arbitrary_points(pairs):
    probs = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]
    cal = IsotonicCalibrator().fit(probs, outcomes)
    # evaluate at a fine grid INCLUDING non-knot points -> must be non-decreasing,
    # bounded in [0, 1] (this is the interpolation path the example tests missed)
    grid = [i / 50 for i in range(51)]
    out = [cal.predict(x) for x in grid]
    assert all(0.0 <= y <= 1.0 for y in out)
    assert all(b >= a - 1e-9 for a, b in zip(out, out[1:]))
