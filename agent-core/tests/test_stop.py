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


def test_budget_condition_tolerates_fp_rounding_at_boundary() -> None:
    """spent + projected == ceiling within FP noise must not produce a false BUDGET stop.

    Without _EPS tolerance, a cycle whose sum lands just above ceiling (e.g.
    100.0 + 1e-15) would be denied even though it is effectively at-boundary.
    """
    cond = BudgetCondition()
    # Exactly at boundary: must be admitted
    assert cond.evaluate(_ctx(spent=50.0, ceiling=100.0, projected_next_cost=50.0)) is None
    # Just below boundary: admitted
    assert cond.evaluate(_ctx(spent=50.0, ceiling=100.0, projected_next_cost=49.999)) is None
    # Clearly over boundary: denied
    out = cond.evaluate(_ctx(spent=50.0, ceiling=100.0, projected_next_cost=51.0))
    assert out is not None and out.reason is StopReason.BUDGET
    # FP noise (< _EPS) at boundary: admitted, not falsely denied
    fp_noise = 1e-15
    noise_ctx = _ctx(spent=50.0, ceiling=100.0, projected_next_cost=50.0 + fp_noise)
    assert cond.evaluate(noise_ctx) is None


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


def test_no_progress_reordered_unresolved_still_stalls() -> None:
    """Reordering of unresolved claims must still be detected as a stall."""
    gate = Gate([NoProgressCondition()])
    result = CycleResult(cost=1.0, new_unresolved=("b", "a"), max_conf_delta=0.1)
    ctx = _ctx(
        cycle_index=2,
        last_result=result,
        prev_unresolved=("a", "b"),  # same claims, different order
    )
    outcome = gate.evaluate(ctx)
    assert outcome is not None and outcome.reason is StopReason.STALL


def test_convergence_skips_first_cycle_with_no_result() -> None:
    """ConvergenceCondition must return None when last_result is None (first cycle)."""
    cond = ConvergenceCondition(0.05)
    assert cond.evaluate(_ctx(last_result=None)) is None


def test_no_progress_skips_when_prev_unresolved_is_none() -> None:
    """NoProgressCondition must return None when prev_unresolved is None (first cycle)."""
    cond = NoProgressCondition()
    res = CycleResult(cost=1, new_unresolved=("a",), max_conf_delta=0.5)
    assert cond.evaluate(_ctx(last_result=res, prev_unresolved=None)) is None


def test_gate_add_enables_fluent_chaining() -> None:
    """Gate.add() must return the Gate itself for fluent chaining and append the condition."""
    gate = Gate([MaxCyclesCondition(3)])
    returned = gate.add(BudgetCondition())
    assert returned is gate
    # the added condition is now evaluated
    out = gate.evaluate(_ctx(cycle_index=1, spent=999, ceiling=1, projected_next_cost=999))
    assert out is not None and out.reason is StopReason.BUDGET


def test_gate_returns_first_non_none():
    # CAP registered before BUDGET: when both fire, CAP wins
    gate = Gate([MaxCyclesCondition(3), BudgetCondition()])
    out = gate.evaluate(_ctx(cycle_index=4, spent=999, ceiling=1, projected_next_cost=999))
    assert out.reason is StopReason.CAP
