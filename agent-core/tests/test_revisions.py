"""Regression tests for the peer-review fixes.

These cover the failure modes the original suite missed: a CostEstimator that
under-projects (the demonstrated breach), gate misconfiguration causing
non-termination, and the zero-cycle admission denial.
"""

import pytest

from agent_core import (
    BudgetExceededError,
    BudgetLedger,
    CycleResult,
    CycleState,
    FrameworkConfig,
    Gate,
    LoopController,
    StopReason,
)


class FixedEstimator:
    def __init__(self, cost):
        self.cost = cost

    def project(self, state):
        return self.cost


class OverspendingProgressingRunner:
    """Costs far more than projected and keeps progressing (the adversarial case)."""

    def __init__(self, cost):
        self.cost = cost
        self._n = 0

    def run(self, state):
        self._n += 1
        return CycleResult(self.cost, (f"x{self._n}",), max_conf_delta=0.5, new_evidence=True)


class CheapNeverConvergingRunner:
    def __init__(self):
        self._n = 0

    def run(self, state):
        self._n += 1
        return CycleResult(1.0, (f"k{self._n}",), max_conf_delta=0.5, new_evidence=True)


# --- the previously-undetected breach is now caught --------------------------
def test_lying_estimator_cannot_breach_reserve_or_cap():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 100.0, "reserve_fraction": 0.2}})
    led = BudgetLedger(cfg)  # ceiling 80, reserve 20, cap 100
    ctrl = LoopController(cfg, led, OverspendingProgressingRunner(cost=70.0), FixedEstimator(5.0))
    res = ctrl.run(CycleState(unresolved=("a",)))

    assert res.reason is StopReason.BUDGET
    assert res.overspent is True
    assert res.spent <= cfg.budget.cap_units  # hard cap held
    assert res.spent <= cfg.loop_ceiling_units  # reserve never touched
    assert res.reserve_available == cfg.reserve_units


# --- termination is guaranteed even with a broken gate -----------------------
def test_aborts_when_admission_gate_misconfigured():
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 5, "absolute_max_cycles": 5}})
    led = BudgetLedger(cfg)
    # empty admission gate => no CAP/BUDGET guard; only the controller backstop saves us
    ctrl = LoopController(
        cfg,
        led,
        CheapNeverConvergingRunner(),
        FixedEstimator(1.0),
        admission_gate=Gate([]),
    )
    res = ctrl.run(CycleState(unresolved=("a",)))
    assert res.reason is StopReason.ABORTED
    assert res.partial is True
    assert res.cycles_completed == 5


# --- zero-cycle admission denial ---------------------------------------------
def test_admission_denied_on_first_cycle_runs_nothing():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 10.0, "reserve_fraction": 0.5}})
    led = BudgetLedger(cfg)  # ceiling 5
    ctrl = LoopController(cfg, led, CheapNeverConvergingRunner(), FixedEstimator(100.0))
    res = ctrl.run(CycleState(unresolved=("a",)))
    assert res.reason is StopReason.BUDGET
    assert res.cycles_completed == 0
    assert res.spent == 0.0


# --- direct ledger enforcement -----------------------------------------------
def test_record_rejects_over_allowance():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 1000.0, "reserve_fraction": 0.1}})
    led = BudgetLedger(cfg)
    with pytest.raises(BudgetExceededError):
        led.record(50.0, allowance=10.0)
    assert led.spent == 0.0  # rejected spend is not applied


def test_record_rejects_cap_breach():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 100.0, "reserve_fraction": 0.0}})
    led = BudgetLedger(cfg)
    led.record(90.0)
    with pytest.raises(BudgetExceededError):
        led.record(20.0)  # 110 > cap 100
    assert led.spent == 90.0


def test_record_within_bounds_succeeds():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 100.0, "reserve_fraction": 0.0}})
    led = BudgetLedger(cfg)
    assert led.record(40.0, allowance=50.0) == 40.0
    assert led.record(30.0, allowance=60.0) == 70.0
