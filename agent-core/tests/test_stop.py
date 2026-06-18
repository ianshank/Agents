from agent_core import (
    BudgetCondition,
    ConvergenceCondition,
    CycleResult,
    FrameworkConfig,
    Gate,
    MaxCyclesCondition,
    NoProgressCondition,
    StopReason,
)
from agent_core.protocols import LoopContext

CFG = FrameworkConfig()


def _ctx(**kw):
    base = dict(
        cycle_index=1,
        config=CFG,
        spent=0.0,
        ceiling=100.0,
        projected_next_cost=0.0,
        last_result=None,
        prev_unresolved=None,
    )
    base.update(kw)
    return LoopContext(**base)


def test_max_cycles_triggers_only_when_exceeded():
    cond = MaxCyclesCondition(5)
    assert cond.evaluate(_ctx(cycle_index=5)) is None
    out = cond.evaluate(_ctx(cycle_index=6))
    assert out is not None and out.reason is StopReason.CAP and out.partial


def test_budget_condition_boundary():
    cond = BudgetCondition()
    assert cond.evaluate(_ctx(spent=80.0, ceiling=100.0, projected_next_cost=20.0)) is None
    out = cond.evaluate(_ctx(spent=80.0, ceiling=100.0, projected_next_cost=20.01))
    assert out is not None and out.reason is StopReason.BUDGET


def test_convergence_requires_low_delta_and_no_new_evidence():
    cond = ConvergenceCondition(0.05)
    converged = CycleResult(cost=1, new_unresolved=(), max_conf_delta=0.0, new_evidence=False)
    assert cond.evaluate(_ctx(last_result=converged)).reason is StopReason.SUCCESS
    still_moving = CycleResult(cost=1, new_unresolved=(), max_conf_delta=0.0, new_evidence=True)
    assert cond.evaluate(_ctx(last_result=still_moving)) is None
    high_delta = CycleResult(cost=1, new_unresolved=(), max_conf_delta=0.5, new_evidence=False)
    assert cond.evaluate(_ctx(last_result=high_delta)) is None


def test_no_progress_detects_unchanged_set():
    cond = NoProgressCondition()
    res = CycleResult(cost=1, new_unresolved=("a", "b"), max_conf_delta=0.5)
    assert (
        cond.evaluate(_ctx(last_result=res, prev_unresolved=("a", "b"))).reason is StopReason.STALL
    )
    assert cond.evaluate(_ctx(last_result=res, prev_unresolved=("a",))) is None


def test_gate_returns_first_non_none():
    # CAP registered before BUDGET: when both fire, CAP wins
    gate = Gate([MaxCyclesCondition(3), BudgetCondition()])
    out = gate.evaluate(_ctx(cycle_index=4, spent=999, ceiling=1, projected_next_cost=999))
    assert out.reason is StopReason.CAP
