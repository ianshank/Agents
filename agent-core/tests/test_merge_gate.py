"""Tests for the calibrated merge-gate decision logic."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from agent_core.calibration import (
    DEFAULT_N_BINS,
    expected_calibration_error,
    reliability_bins,
)
from agent_core.config import ConfigError
from agent_core.merge_gate import (
    CalibratorHealth,
    ChangeContext,
    GateDecision,
    GatePolicyConfig,
    _wilson_bound,
    decide,
    threshold_for_risk,
)
from agent_core.outcome_store import BinningCalibrator

CFG = GatePolicyConfig()


class _Const:
    """Calibrator returning a fixed probability regardless of input."""

    def __init__(self, p: float) -> None:
        self._p = p

    def predict(self, raw_score: float) -> float:
        return self._p


def _healthy() -> CalibratorHealth:
    return CalibratorHealth(n=2000, ece=0.02, auroc=0.9, bin_ci_width=0.05)


# --- _wilson_bound -----------------------------------------------------------
def test_wilson_bound_zero_n():
    # Delegates to calibration.wilson_interval, which returns (0, 0) for n == 0;
    # the lower bound (0.0) is what the gate's Wilson floor relies on (=> ESCALATE).
    assert _wilson_bound(0, 0, 1.96, lower=True) == 0.0
    assert _wilson_bound(0, 0, 1.96, lower=False) == 0.0


def test_wilson_bound_lower_below_upper():
    lo = _wilson_bound(8, 10, 1.96, lower=True)
    hi = _wilson_bound(8, 10, 1.96, lower=False)
    assert 0.0 <= lo < hi <= 1.0


# --- CalibratorHealth.is_trustworthy ----------------------------------------
def test_health_trustworthy_true():
    assert _healthy().is_trustworthy(CFG)


def test_health_untrustworthy_each_condition():
    assert not CalibratorHealth(n=10, ece=0.02, auroc=0.9, bin_ci_width=0.05).is_trustworthy(CFG)
    assert not CalibratorHealth(n=2000, ece=0.5, auroc=0.9, bin_ci_width=0.05).is_trustworthy(CFG)
    assert not CalibratorHealth(n=2000, ece=0.02, auroc=0.5, bin_ci_width=0.05).is_trustworthy(CFG)
    assert not CalibratorHealth(n=2000, ece=0.02, auroc=0.9, bin_ci_width=0.9).is_trustworthy(CFG)


# --- threshold_for_risk ------------------------------------------------------
def test_threshold_none_when_empty():
    assert threshold_for_risk([], [], CFG) is None


def test_threshold_found_for_clean_separation():
    # 200 clearly-correct high scores + 200 clearly-incorrect low scores.
    scores = [0.95] * 200 + [0.1] * 200
    correct = [True] * 200 + [False] * 200
    tau = threshold_for_risk(scores, correct, CFG)
    assert tau is not None and tau >= 0.95


def test_threshold_none_when_risk_unachievable():
    # Everything is a coin flip; no tau achieves a 2% risk ceiling.
    scores = [0.5] * 100
    correct = [i % 2 == 0 for i in range(100)]
    assert threshold_for_risk(scores, correct, CFG) is None


# --- decide ------------------------------------------------------------------
def _ctx(**kw: object) -> ChangeContext:
    base: dict[str, Any] = dict(
        mech_pass=True, touches_protected=False, raw_confidence=0.99, domain="core"
    )
    base.update(kw)
    return ChangeContext(**base)


def test_decide_reject_on_mech_fail():
    assert decide(_ctx(mech_pass=False), _Const(0.99), _healthy(), 0.9, 100, 100, CFG) == (
        GateDecision.REJECT
    )


def test_decide_escalate_on_protected():
    assert decide(_ctx(touches_protected=True), _Const(0.99), _healthy(), 0.9, 100, 100, CFG) == (
        GateDecision.ESCALATE
    )


def test_decide_protected_auto_merge_when_explicitly_enabled():
    cfg = GatePolicyConfig(protected_auto_merge=True)
    d = decide(_ctx(touches_protected=True), _Const(0.99), _healthy(), 0.5, 100, 100, cfg)
    assert d == GateDecision.AUTO_MERGE


def test_decide_escalate_on_cold_start():
    assert decide(_ctx(), None, None, None, 0, 0, CFG) == GateDecision.ESCALATE


def test_decide_escalate_on_unhealthy():
    thin = CalibratorHealth(n=10, ece=0.02, auroc=0.9, bin_ci_width=0.05)
    assert decide(_ctx(), _Const(0.99), thin, 0.9, 100, 100, CFG) == GateDecision.ESCALATE


def test_decide_escalate_when_p_below_tau():
    assert decide(_ctx(), _Const(0.80), _healthy(), 0.95, 100, 100, CFG) == GateDecision.ESCALATE


def test_decide_escalate_on_thin_bin_floor():
    # p >= tau and healthy, but the bin is tiny so its Wilson-lower is below floor.
    assert decide(_ctx(), _Const(0.99), _healthy(), 0.5, 1, 1, CFG) == GateDecision.ESCALATE


def test_decide_auto_merge_happy_path():
    assert decide(_ctx(), _Const(0.99), _healthy(), 0.5, 1000, 1000, CFG) == (
        GateDecision.AUTO_MERGE
    )


def test_gate_decision_values():
    assert GateDecision.AUTO_MERGE.value == "auto_merge"
    assert GateDecision.ESCALATE.value == "escalate"
    assert GateDecision.REJECT.value == "reject"


# --- ChangeContext input contract -------------------------------------------
@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf"), 1.0000001, 5.0, -0.1],
    ids=["nan", "inf", "-inf", "just-above-1", "far-above-1", "below-0"],
)
def test_change_context_rejects_out_of_contract_confidence(bad: float) -> None:
    """The gate must never be handed a confidence it cannot interpret.

    Regression test for a one-sided fail-open: NaN compares False against every bin
    edge, so it fell through to the *top* bin and, with a trustworthy calibrator,
    produced AUTO_MERGE -- as did any value above 1.0. Values below 0 escalated, so
    only the unsafe direction was silent.
    """
    with pytest.raises(ValueError, match="raw_confidence"):
        ChangeContext(mech_pass=True, touches_protected=False, raw_confidence=bad, domain="core")


@pytest.mark.parametrize("ok", [0.0, 0.5, 1.0])
def test_change_context_accepts_the_documented_range(ok: float) -> None:
    ctx = ChangeContext(mech_pass=True, touches_protected=False, raw_confidence=ok, domain="core")
    assert ctx.raw_confidence == ok


# --- GatePolicyConfig validation ---------------------------------------------
@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Vacuous endpoints: a floor that can never reject is a lie about the check.
        ("risk_target", 1.0),
        ("max_ece", 1.0),
        ("max_bin_ci_width", 1.0),
        ("wilson_floor", 0.0),
        ("min_calibration_n", 0),
        # `min_auroc <= 0.5` silently readmits single-class domains: build_domain_models
        # substitutes the sentinel 0.5 when only one class is present, and its comment
        # claims that "fails the health floor" -- true only while this bound holds.
        ("min_auroc", 0.5),
        ("min_auroc", 0.0),
        # A single bin makes predict() constant, tau equal to it, and every change clear.
        ("n_bins", 1),
        ("n_bins", 0),
        # Out of range on the other side.
        ("risk_target", -0.1),
        ("max_ece", -0.1),
        ("min_auroc", 1.1),
        ("wilson_floor", 1.1),
        ("min_calibration_n", -1),
        ("risk_ci_z", 0.0),
        ("wilson_z", 0.0),
        ("wilson_z", -1.0),
        # Non-finite. NaN compares False against every bound, so an unguarded range
        # test would PASS it -- the one-sided fail-open this subsystem keeps hitting.
        ("risk_target", float("nan")),
        ("max_ece", float("nan")),
        ("min_auroc", float("nan")),
        ("wilson_z", float("nan")),
        ("wilson_z", float("inf")),
        ("max_bin_ci_width", float("inf")),
    ],
)
def test_gate_policy_rejects_out_of_range(field: str, value: Any) -> None:
    """Every tunable that governs autonomy is bounded, and says what it got.

    Before this, GatePolicyConfig was the only agent-core config without a
    __post_init__ -- it accepted risk_target=1.0 (which collapses tau to the smallest
    observed score, auto-merging everything) and min_calibration_n=0.
    """
    with pytest.raises(ConfigError, match=field) as exc:
        GatePolicyConfig(**{field: value})
    assert repr(value) in str(exc.value), "the message must echo the offending value"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # The maximally-STRICT endpoint of each range is legal: it is a kill switch,
        # not a fail-open, and an operator may legitimately want one.
        ("risk_target", 0.0),
        ("max_ece", 0.0),
        ("max_bin_ci_width", 0.0),
        ("min_auroc", 1.0),
        ("wilson_floor", 1.0),
        ("min_calibration_n", 1),
        ("n_bins", 2),
    ],
)
def test_gate_policy_accepts_the_strict_endpoints(field: str, value: Any) -> None:
    assert getattr(GatePolicyConfig(**{field: value}), field) == value


def test_gate_policy_defaults_are_valid() -> None:
    """Guards against a future default drifting outside its own documented bound."""
    assert GatePolicyConfig().n_bins == DEFAULT_N_BINS


def test_bin_count_defaults_are_single_sourced() -> None:
    """The three histogram implementations must not re-type the bin count.

    They agreed only by coincidence before: `10` was written independently in
    BinningCalibrator.fit, the gate's CI-width scan, and expected_calibration_error,
    and build_domain_models passed none of them. Changing one would silently desync
    the calibrator from the ECE that measures it.
    """
    defaults = {
        inspect.signature(reliability_bins).parameters["n_bins"].default,
        inspect.signature(expected_calibration_error).parameters["n_bins"].default,
        inspect.signature(BinningCalibrator.fit).parameters["bins"].default,
        GatePolicyConfig().n_bins,
    }
    assert defaults == {DEFAULT_N_BINS}
