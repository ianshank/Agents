"""Tests for the calibrated merge-gate decision logic."""

from __future__ import annotations

from typing import Any

from agent_core.merge_gate import (
    CalibratorHealth,
    ChangeContext,
    GateDecision,
    GatePolicyConfig,
    _wilson_bound,
    decide,
    threshold_for_risk,
)

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
