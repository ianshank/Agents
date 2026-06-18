"""Loop integration tests.

Deterministic CycleRunner doubles drive the *real* control logic through each of
the four exit paths. No part of the controller is mocked.
"""

from agent_core import (
    BudgetLedger,
    CycleResult,
    CycleState,
    FrameworkConfig,
    LoopController,
    StopReason,
)


class FixedEstimator:
    def __init__(self, cost):
        self.cost = cost

    def project(self, state):
        return self.cost


class ConvergingRunner:
    """Resolves a claim each cycle; converges at `converge_at`."""

    def __init__(self, converge_at=3, cost=10.0):
        self.converge_at = converge_at
        self.cost = cost

    def run(self, state: CycleState) -> CycleResult:
        remaining = state.unresolved[1:]  # drop one each cycle (always changes)
        if state.cycle_index >= self.converge_at:
            return CycleResult(self.cost, (), max_conf_delta=0.0, new_evidence=False)
        return CycleResult(self.cost, remaining, max_conf_delta=0.5, new_evidence=True)


class FlatExpensiveRunner:
    """Never converges; flat high cost; always makes nominal progress."""

    def __init__(self, cost=30.0):
        self.cost = cost
        self._n = 0

    def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        return CycleResult(self.cost, (f"c{self._n}",), max_conf_delta=0.5, new_evidence=True)


class StallRunner:
    """Returns the same unresolved set it received -> no progress."""

    def run(self, state: CycleState) -> CycleResult:
        return CycleResult(1.0, tuple(state.unresolved), max_conf_delta=0.5, new_evidence=True)


class CapRunner:
    """Progresses every cycle, never converges, cheap -> hits max_cycles."""

    def __init__(self):
        self._n = 0

    def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        return CycleResult(1.0, (f"k{self._n}",), max_conf_delta=0.5, new_evidence=True)


def _controller(cfg, runner, estimator):
    return LoopController(cfg, BudgetLedger(cfg), runner, estimator)


def test_success_path():
    cfg = FrameworkConfig()  # big budget, max_cycles 5
    ctrl = _controller(cfg, ConvergingRunner(converge_at=3), FixedEstimator(10.0))
    res = ctrl.run(CycleState(cycle_index=1, unresolved=("a", "b", "c")))
    assert res.reason is StopReason.SUCCESS
    assert res.partial is False
    assert res.cycles_completed == 3


def test_budget_denies_before_overshoot():
    cfg = FrameworkConfig.from_dict(
        {"budget": {"cap_units": 100.0, "reserve_fraction": 0.2}}  # ceiling 80
    )
    ctrl = _controller(cfg, FlatExpensiveRunner(cost=30.0), FixedEstimator(30.0))
    res = ctrl.run(CycleState(cycle_index=1, unresolved=("a",)))
    assert res.reason is StopReason.BUDGET
    assert res.partial is True
    assert res.cycles_completed == 2  # cycle 3 denied admission
    assert res.spent <= cfg.loop_ceiling_units  # never overshot
    assert res.reserve_available == cfg.reserve_units  # reserve intact


def test_stall_path():
    cfg = FrameworkConfig()
    ctrl = _controller(cfg, StallRunner(), FixedEstimator(1.0))
    res = ctrl.run(CycleState(cycle_index=1, unresolved=("x", "y")))
    assert res.reason is StopReason.STALL
    assert res.partial is True
    assert res.cycles_completed == 1


def test_cap_backstop_path():
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 3}})
    ctrl = _controller(cfg, CapRunner(), FixedEstimator(1.0))
    res = ctrl.run(CycleState(cycle_index=1, unresolved=("a",)))
    assert res.reason is StopReason.CAP
    assert res.cycles_completed == 3


def test_run_cycles_completed_from_nonzero_initial_cycle_index() -> None:
    """cycles_completed counts cycles run in THIS call, not absolute cycle_index."""
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 10}})
    # ConvergingRunner with converge_at=1 converges immediately when cycle_index >= 1
    ctrl = _controller(cfg, ConvergingRunner(converge_at=1), FixedEstimator(1.0))
    initial = CycleState(cycle_index=5, unresolved=("x",))  # resumed from cycle 5
    result = ctrl.run(initial)
    assert result.reason is StopReason.SUCCESS
    assert result.cycles_completed == 1  # ran 1 cycle, not 5
