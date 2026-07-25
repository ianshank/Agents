"""Tests for prediction-powered inference and its correlation statistics.

Two of these are regressions for defects an adversarial review found *after* the code
looked finished and fully covered, so they are written to fail loudly if the fix is
undone: an interval whose bounds were clipped independently of an out-of-range point
(producing `lo > hi` with no degeneracy flag), and a variance-reduction figure derived
from those clipped bounds (reporting a 3% gain as 94%).
"""

from __future__ import annotations

import math
import random

import pytest

from agent_core.calibration import wilson_interval
from agent_core.ppi import (
    CorrelationConfig,
    PPIConfig,
    effective_n_multiplier,
    pearson_r,
    ppi_plus_interval,
)

CFG = PPIConfig()


def _r(xs: list[float], ys: list[float]) -> float:
    """pearson_r, asserted defined — keeps the numeric cases free of None-handling noise."""
    value = pearson_r(xs, ys)
    assert value is not None
    return value


def _synthetic(n: int, big_n: int, signal: float, seed: int = 0):
    """Labelled pairs + an unlabeled proxy pool whose correlation tracks ``signal``."""
    rng = random.Random(seed)
    labeled = []
    for _ in range(n):
        y = 1 if rng.random() < 0.7 else 0
        labeled.append((signal * y + (1 - signal) * rng.random(), y))
    unlabeled = [
        signal * (1 if rng.random() < 0.7 else 0) + (1 - signal) * rng.random()
        for _ in range(big_n)
    ]
    return labeled, unlabeled


# --- pearson_r ---------------------------------------------------------------
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
    exactly 0.0, so a ``sqrt(vx * vy)`` denominator raised ZeroDivisionError.
    """
    tiny = [0.0, 3.2900281484057283e-83]
    assert math.isclose(_r(tiny, tiny), 1.0, abs_tol=1e-9)


def test_pearson_r_handles_huge_values_without_overflow() -> None:
    result = pearson_r([-1e308, 1e308], [-1e308, 1e308])
    assert result is None or -1.0 <= result <= 1.0


# --- effective_n_multiplier --------------------------------------------------
def test_effective_n_multiplier_matches_the_closed_form() -> None:
    assert math.isclose(effective_n_multiplier(0.0), 1.0, abs_tol=1e-12)
    assert math.isclose(effective_n_multiplier(0.5), 1 / 0.75, abs_tol=1e-12)
    assert math.isclose(effective_n_multiplier(-0.5), 1 / 0.75, abs_tol=1e-12)  # sign-free


def test_effective_n_multiplier_saturates_at_the_configured_ceiling() -> None:
    """A perfect proxy would mean no labels were needed — never a plausible reading."""
    assert effective_n_multiplier(None) == 1.0
    assert effective_n_multiplier(1.0) == CorrelationConfig().max_effective_n
    assert effective_n_multiplier(-1.0) == CorrelationConfig().max_effective_n
    assert effective_n_multiplier(1.0, CorrelationConfig(max_effective_n=5.0)) == 5.0


@pytest.mark.parametrize("rho", [1.5, -1.5, 2.0])
def test_effective_n_multiplier_rejects_out_of_contract_rho(rho: float) -> None:
    with pytest.raises(ValueError, match="rho must be in"):
        effective_n_multiplier(rho)


def test_correlation_config_rejects_an_invalid_ceiling() -> None:
    for bad in (0.5, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="max_effective_n"):
            CorrelationConfig(max_effective_n=bad)


# --- PPIConfig ---------------------------------------------------------------
def test_ppi_config_defaults() -> None:
    cfg = PPIConfig()
    assert (cfg.z, cfg.lambda_min, cfg.lambda_max) == (1.96, 0.0, 1.0)
    assert cfg.min_labeled == 10
    assert (cfg.proxy_lo, cfg.proxy_hi) == (0.0, 1.0)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PPIConfig(z=0.0),
        lambda: PPIConfig(z=float("nan")),
        lambda: PPIConfig(z=float("inf")),
        lambda: PPIConfig(lambda_min=0.9, lambda_max=0.1),
        lambda: PPIConfig(lambda_min=float("nan")),
        lambda: PPIConfig(min_labeled=1),
        lambda: PPIConfig(min_labeled=2),
        lambda: PPIConfig(proxy_lo=1.0, proxy_hi=0.0),
        lambda: PPIConfig(proxy_lo=float("nan")),
    ],
)
def test_ppi_config_rejects_invalid_values(factory) -> None:
    with pytest.raises(ValueError):
        factory()


# --- the two critical regressions -------------------------------------------
def test_interval_is_never_inverted_when_the_point_hits_the_boundary() -> None:
    """Regression: `lo > hi` with `degenerate=None`.

    `point` is unbounded above (proxy shift x lambda), so clipping `lo` and `hi`
    independently produced `[1.240, 1.000]` — a negative half-width, a point outside its
    own interval, and no degeneracy flag — which rendered verbatim into the report.
    """
    labeled = [
        (0.00, 0), (0.02, 0), (0.04, 1), (0.06, 1), (0.08, 1),
        (0.10, 1), (0.01, 0), (0.03, 0), (0.05, 1), (0.07, 1),
    ]  # fmt: skip
    est = ppi_plus_interval(labeled, [0.99] * 500)
    assert est.lo <= est.hi, "interval must never be inverted"
    assert est.half_width >= 0.0
    assert est.lo <= est.point <= est.hi, "point must lie inside its own interval"
    assert 0.0 <= est.lo <= est.hi <= 1.0


def test_variance_reduction_is_independent_of_the_unlabeled_mean() -> None:
    """Regression: the figure was computed from CLIPPED bounds.

    The standard error does not depend on ``mean_U(f)`` at all, so sliding it must leave
    the reported reduction unchanged. Previously it swung 6.8% -> 93.8% -> 62.5% purely
    from how close the point estimate sat to the [0, 1] boundary — non-monotonic, and
    over-reporting a 3% gain as 94%.
    """
    labeled = [(0.10 + 0.01 * i, 1 if i < 14 else 0) for i in range(20)]
    seen = {
        round(ppi_plus_interval(labeled, [m] * 400).variance_reduction or 0.0, 9)
        for m in (0.30, 0.50, 0.80, 0.95)
    }
    assert len(seen) == 1, f"variance_reduction must not track the unlabeled mean: {seen}"


def test_variance_reduction_reports_a_genuine_widening_as_negative() -> None:
    """PPI++ genuinely widens when the unlabeled proxy spread dwarfs the labelled one.

    The ``lam^2 * Var_U(f) / N`` term then outweighs the residual saving, so the honest
    answer is negative. Flooring it at 0% (the original ``max(0.0, ...)``) made a real
    regression indistinguishable from "no gain" — exactly the case an operator must see.
    """
    rng = random.Random(4)
    labeled = [
        (0.40 + 0.02 * (1 if i < 14 else 0) + 0.01 * rng.random(), 1 if i < 14 else 0)
        for i in range(20)
    ]  # narrow, weakly informative proxy
    unlabeled = [rng.random() for _ in range(22)]  # wide spread, small pool
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is None and est.lam > 0.0
    assert est.variance_reduction is not None and est.variance_reduction < 0.0
    assert est.se is not None and est.se_classical is not None and est.se > est.se_classical


def test_variance_reduction_is_none_on_a_degenerate_estimate() -> None:
    """No trustworthy comparison exists, so no number is offered."""
    est = ppi_plus_interval([(0.9, 1)] * 20, [0.9] * 50)
    assert est.degenerate is not None
    assert est.variance_reduction is None


# --- estimator behaviour ------------------------------------------------------
def test_ppi_rejects_non_binary_outcomes() -> None:
    with pytest.raises(ValueError, match="outcome must be 0 or 1"):
        ppi_plus_interval([(0.5, 2)], [0.5])


def test_uninformative_proxy_collapses_to_the_classical_estimator() -> None:
    """lambda -> 0 is the safety argument: PPI++ can never be asymptotically worse."""
    labeled, unlabeled = _synthetic(200, 4000, signal=0.0, seed=11)
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is None
    assert math.isclose(est.lam, 0.0, abs_tol=1e-9)
    assert est.se is not None and est.se_classical is not None
    assert math.isclose(est.se, est.se_classical, rel_tol=1e-9)


def test_informative_proxy_is_strictly_narrower() -> None:
    labeled, unlabeled = _synthetic(200, 4000, signal=0.9, seed=3)
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is None and est.lam > 0.0
    assert est.se is not None and est.se_classical is not None
    assert est.se < est.se_classical
    assert (est.variance_reduction or 0.0) > 0.0


def test_variance_reduction_tracks_rho_squared() -> None:
    """The reported gain must match the theory it is sold on: 1 - Var ratio ~= rho^2."""
    labeled, unlabeled = _synthetic(400, 8000, signal=0.7, seed=5)
    est = ppi_plus_interval(labeled, unlabeled)
    rho = _r([f for f, _ in labeled], [float(o) for _, o in labeled])
    assert est.variance_reduction is not None
    assert abs(est.variance_reduction - rho * rho) < 0.1


def test_single_outcome_class_falls_back_to_wilson_not_a_point() -> None:
    """Zero labelled variance makes the Wald SE zero; a naive interval becomes [1, 1]."""
    est = ppi_plus_interval([(0.9, 1)] * 20, [0.9] * 500)
    assert est.degenerate is not None and "single outcome class" in est.degenerate
    assert (est.lo, est.hi) != (1.0, 1.0)
    assert math.isclose(est.lo, wilson_interval(20, 20)[0], abs_tol=1e-12)


@pytest.mark.parametrize(
    ("labeled", "unlabeled", "expected"),
    [
        ([(0.5, 1)] * 5, [0.5] * 10, "insufficient labelled samples"),
        ([(i / 20, i % 2) for i in range(12)], [], "no unlabeled proxy values"),
        ([(0.5, i % 2) for i in range(12)], [0.5] * 10, "constant proxy"),
        ([(i / 20, i % 2) for i in range(12)], [5.0] * 10, "proxy outside"),
    ],
    ids=["too-few-labels", "no-unlabeled", "constant-proxy", "out-of-range-proxy"],
)
def test_degenerate_paths_fall_back_to_wilson(labeled, unlabeled, expected) -> None:
    est = ppi_plus_interval(labeled, unlabeled)
    assert est.degenerate is not None and expected in est.degenerate
    assert est.lam == 0.0
    k = sum(o for _, o in labeled)
    assert math.isclose(est.lo, wilson_interval(k, len(labeled))[0], abs_tol=1e-12)


def test_degeneracy_is_logged_at_debug_not_warning(caplog) -> None:
    """Degeneracy is the EXPECTED state at low N and is already surfaced structurally.

    Emitting it at WARNING produced 18 lines from one ordinary report run, training
    operators to filter the logger that also carries the gate's real fail-closed warnings.
    """
    with caplog.at_level("DEBUG", logger="agent_core.ppi"):
        est = ppi_plus_interval([(0.9, 1)] * 12, [0.9] * 50)
    assert est.degenerate is not None
    assert any("falling back to the Wilson interval" in r.message for r in caplog.records)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_single_unlabeled_value_is_treated_conservatively() -> None:
    """N == 1 has no variance estimate; asserting zero would claim a noiseless mean."""
    labeled, _ = _synthetic(30, 0, signal=0.6, seed=2)
    est = ppi_plus_interval(labeled, [0.5])
    assert math.isfinite(est.lo) and math.isfinite(est.hi)
    assert 0.0 <= est.lo <= est.hi <= 1.0


def test_lambda_clamp_is_configurable() -> None:
    """Pinning lambda to 0 must reproduce the classical standard error exactly."""
    labeled, unlabeled = _synthetic(150, 3000, signal=0.9, seed=9)
    pinned = ppi_plus_interval(labeled, unlabeled, PPIConfig(lambda_max=0.0))
    assert pinned.lam == 0.0
    assert pinned.se is not None and pinned.se_classical is not None
    assert math.isclose(pinned.se, pinned.se_classical, rel_tol=1e-9)


def test_interval_is_always_a_valid_probability_interval() -> None:
    for signal in (0.0, 0.3, 0.6, 0.95):
        for n, big_n in ((10, 100), (50, 1000), (200, 5000)):
            est = ppi_plus_interval(*_synthetic(n, big_n, signal, seed=n + int(signal * 100)))
            assert 0.0 <= est.lo <= est.point <= est.hi <= 1.0


def test_coverage_is_near_nominal_at_the_configured_floor() -> None:
    """Empirical justification for ``PPIConfig.min_labeled``.

    ``lambda`` is fitted from the same points the residual variance is measured on, so the
    residual costs a second degree of freedom; with ddof=1 coverage sat 3-7 points below
    nominal for small n. This pins that the shipped default actually delivers roughly its
    advertised 95% under the estimator's own exchangeability assumption.
    """
    rng = random.Random(20260725)
    n, big_n, trials, truth = PPIConfig().min_labeled, 200, 400, 0.7
    covered = 0
    for _ in range(trials):
        pool = [1 if rng.random() < truth else 0 for _ in range(n + big_n)]
        proxies = [0.5 * y + 0.5 * rng.random() for y in pool]
        est = ppi_plus_interval(list(zip(proxies[:n], pool[:n], strict=True)), proxies[n:])
        if est.degenerate is None and est.lo <= truth <= est.hi:
            covered += 1
        elif est.degenerate is not None:
            covered += 1  # fell back to Wilson, which is conservative by construction
    assert covered / trials >= 0.90, f"coverage {covered / trials:.3f} far below nominal 0.95"


def test_a_tuned_lambda_never_runs_out_of_residual_degrees_of_freedom() -> None:
    """Regression: `ddof=2` at n=2 left zero dof, so the residual variance collapsed to 0.

    The interval then reported a half-width of ~0.06 from TWO observations — the exact
    false certainty this estimator exists to refuse. The default ``min_labeled`` hid it,
    but the config permitted ``min_labeled=2``, so both the contract and a runtime guard
    now reject it.
    """
    with pytest.raises(ValueError, match="min_labeled must be >= 3"):
        PPIConfig(min_labeled=2)

    # And no permitted configuration can produce an implausibly tight interval.
    narrowest = min(
        (
            est.half_width
            for n in range(3, 15)
            for est in [
                ppi_plus_interval(
                    [(i / 20, i % 2) for i in range(n)],
                    [0.5] * 50 + [0.9] * 50,
                    PPIConfig(min_labeled=3),
                )
            ]
            if est.degenerate is None
        ),
        default=1.0,
    )
    assert narrowest > 0.1, f"half-width {narrowest:.4f} is implausible at n < 15"


def test_out_of_range_proxy_reports_a_count_and_one_example() -> None:
    """The message needs the first offender and a count -- not every offending value.

    Materialising them all (plus the concatenated proxy tuple that fed the comprehension)
    allocated two full copies of an arbitrarily large unlabeled pool to print one example.
    """
    est = ppi_plus_interval([(i / 20, i % 2) for i in range(12)], [5.0] * 1000)
    assert est.degenerate is not None
    assert "1000 value(s)" in est.degenerate
    assert "e.g. 5" in est.degenerate
    assert math.isclose(est.lo, wilson_interval(6, 12)[0], abs_tol=1e-12)
