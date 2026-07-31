"""Property-based tests.

Example tests catch the bugs you thought of; these catch the ones you didn't.
Invariants asserted over randomised inputs: metric ranges, and isotonic
monotonicity evaluated at *non-knot* points (the gap the review flagged).
"""

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_core import (
    IsotonicCalibrator,
    auroc,
    brier_score,
    effective_n_multiplier,
    expected_calibration_error,
    maximum_calibration_error,
    pearson_r,
    ppi_plus_interval,
    wilson_interval,
)
from agent_core.audit_sampler import inclusion_probability

probs_st = st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=1, max_size=200)


def _outcomes(n, data):
    return [data.draw(st.integers(0, 1)) for _ in range(n)]


@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=1,
        max_size=200,
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
        min_size=1,
        max_size=200,
    )
)
def test_brier_in_unit_interval(pairs):
    probs = [p for p, _ in pairs]
    outcomes = [o for _, o in pairs]
    assert 0.0 <= brier_score(probs, outcomes) <= 1.0


@given(
    pairs=st.lists(
        st.tuples(st.floats(min_value=0.0, max_value=1.0), st.integers(0, 1)),
        min_size=2,
        max_size=200,
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
        min_size=2,
        max_size=200,
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
    assert all(b >= a - 1e-9 for a, b in pairwise(out))


# --- prediction-powered inference --------------------------------------------
_UNIT = st.floats(min_value=0.0, max_value=1.0)


# The estimator accepts ANY finite proxy, so the strategy must too -- confining it to
# [0, 1] is what let an inverted-interval bug (lo > hi) survive a "fully covered" suite.
_ANY = st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6)


@given(
    pairs=st.lists(st.tuples(_ANY, st.integers(0, 1)), min_size=1, max_size=200),
    unlabeled=st.lists(_ANY, max_size=400),
)
def test_ppi_interval_is_always_a_valid_probability_interval(pairs, unlabeled):
    """Whatever the input, the interval must stay a usable probability interval."""
    est = ppi_plus_interval(pairs, unlabeled)
    assert 0.0 <= est.lo <= est.hi <= 1.0
    assert 0.0 <= est.point <= 1.0
    assert 0.0 <= est.lam <= 1.0
    assert est.lo <= est.point <= est.hi, "point must lie inside its own interval"
    assert est.half_width >= 0.0


@given(
    pairs=st.lists(st.tuples(_ANY, st.integers(0, 1)), min_size=1, max_size=200),
    unlabeled=st.lists(_ANY, max_size=400),
)
def test_ppi_degenerate_results_are_exactly_wilson(pairs, unlabeled):
    """The fail-closed contract: a degenerate estimate is never tighter than Wilson.

    This is the invariant that stops a zero-variance slice from reporting false
    certainty — the single most dangerous failure mode of a Wald-type interval.
    """
    est = ppi_plus_interval(pairs, unlabeled)
    if est.degenerate is not None:
        k = sum(o for _, o in pairs)
        lo, hi = wilson_interval(k, len(pairs))
        assert abs(est.lo - lo) < 1e-12
        assert abs(est.hi - hi) < 1e-12
        assert est.lam == 0.0


@given(
    xs=st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=0, max_size=100),
    ys=st.lists(st.floats(min_value=-1e6, max_value=1e6), min_size=0, max_size=100),
)
def test_pearson_r_is_bounded_or_undefined(xs, ys):
    n = min(len(xs), len(ys))
    r = pearson_r(xs[:n], ys[:n])
    assert r is None or -1.0 <= r <= 1.0


@given(rho=st.one_of(st.none(), st.floats(min_value=-1.0, max_value=1.0)))
def test_effective_n_multiplier_is_finite_and_at_least_one(rho):
    m = effective_n_multiplier(rho)
    assert m >= 1.0
    assert m == m and m != float("inf")  # finite, never NaN


@given(
    n=st.integers(min_value=0, max_value=500),
    floor=st.integers(min_value=-5, max_value=500),
    rate=_UNIT,
)
def test_inclusion_probability_is_bounded(n, floor, rate):
    p = inclusion_probability(n, floor, rate)
    assert 0.0 <= p <= 1.0
    if n > 0:
        assert p >= rate  # the floor can only improve a record's odds
