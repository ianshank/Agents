"""Stop conditions and gate evaluators.

The four stop conditions are independent, registrable objects implementing the
:class:`StopCondition` protocol. A :class:`Gate` evaluates an ordered list of
them with first-true-wins semantics. Adding a new stop rule means writing a
condition and registering it — the loop never changes (open/closed principle).
"""

from __future__ import annotations

from collections.abc import Sequence

from .protocols import LoopContext, StopCondition, StopOutcome, StopReason


class MaxCyclesCondition:
    """Admission-phase: refuse to start a cycle beyond the configured backstop."""

    def __init__(self, max_cycles: int) -> None:
        self._max = max_cycles

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None:
        if ctx.cycle_index > self._max:
            return StopOutcome(
                StopReason.CAP,
                detail=f"cycle {ctx.cycle_index} exceeds max_cycles={self._max}",
                partial=True,
            )
        return None


class BudgetCondition:
    """Admission-phase: refuse a cycle whose projected cost breaks the ceiling."""

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None:
        if (ctx.spent + ctx.projected_next_cost) > ctx.ceiling:
            return StopOutcome(
                StopReason.BUDGET,
                detail=(
                    f"spent={ctx.spent:.1f} + projected={ctx.projected_next_cost:.1f} "
                    f"> ceiling={ctx.ceiling:.1f}"
                ),
                partial=True,
            )
        return None


class ConvergenceCondition:
    """Outcome-phase: succeed when confidence stabilises and no new refutation appears."""

    def __init__(self, epsilon: float) -> None:
        self._eps = epsilon

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None:
        r = ctx.last_result
        if r is None:
            return None
        if r.max_conf_delta < self._eps and not r.new_evidence:
            return StopOutcome(
                StopReason.SUCCESS,
                detail=f"converged: delta={r.max_conf_delta:.4f} < eps={self._eps}",
                partial=False,
            )
        return None


class NoProgressCondition:
    """Outcome-phase: stall when the unresolved set is unchanged since last cycle."""

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None:
        r = ctx.last_result
        if r is None or ctx.prev_unresolved is None:
            return None
        if set(r.new_unresolved) == set(ctx.prev_unresolved):
            return StopOutcome(
                StopReason.STALL,
                detail="unresolved set unchanged since previous cycle",
                partial=True,
            )
        return None


class Gate:
    """Evaluates an ordered list of conditions; first non-None outcome wins."""

    def __init__(self, conditions: Sequence[StopCondition]) -> None:
        self._conditions: list[StopCondition] = list(conditions)

    def add(self, condition: StopCondition) -> Gate:
        self._conditions.append(condition)
        return self

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None:
        for cond in self._conditions:
            outcome = cond.evaluate(ctx)
            if outcome is not None:
                return outcome
        return None
