"""The verifier loop controller.

Implements the corrected two-gate control flow:

  ADMISSION gate (before each cycle)  -> may exit CAP / BUDGET
  run cycle (injected CycleRunner, granted a hard spend allowance)
  OUTCOME check (after each cycle)     -> may exit SUCCESS / STALL

Hardened per peer review:
  * each cycle is granted an explicit spend allowance; the ledger rejects a
    runner that exceeds it, so a lying CostEstimator can no longer breach the
    reserve — the run finalises BUDGET (overspent) instead.
  * a controller-level absolute cycle limit guarantees termination even if the
    injected gates are misconfigured (e.g. someone drops MaxCyclesCondition).

The controller is generic: it knows nothing about how verification works, only
the CycleRunner / CostEstimator protocols. All thresholds come from config.
"""

from __future__ import annotations

from dataclasses import dataclass

from .budget import BudgetExceededError, BudgetLedger
from .config import FrameworkConfig
from .logging_util import debug_span, get_logger
from .protocols import (
    CostEstimator,
    CycleResult,
    CycleRunner,
    CycleState,
    LoopContext,
    StopOutcome,
    StopReason,
)
from .stop import (
    BudgetCondition,
    ConvergenceCondition,
    Gate,
    MaxCyclesCondition,
    NoProgressCondition,
)


@dataclass(frozen=True)
class RunResult:
    reason: StopReason
    partial: bool
    cycles_completed: int
    spent: float
    reserve_available: float
    final_state: CycleState
    detail: str = ""
    overspent: bool = False  # True if a runner exceeded its granted allowance


class LoopController:
    def __init__(
        self,
        config: FrameworkConfig,
        ledger: BudgetLedger,
        runner: CycleRunner,
        estimator: CostEstimator,
        admission_gate: Gate | None = None,
        outcome_check: Gate | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._runner = runner
        self._estimator = estimator
        # Default gates are built from config but fully overridable for testing
        # or to register additional conditions.
        self._admission = admission_gate or Gate(
            [
                MaxCyclesCondition(config.loop.max_cycles),
                BudgetCondition(),
            ]
        )
        self._outcome = outcome_check or Gate(
            [
                ConvergenceCondition(config.loop.convergence_epsilon),
                NoProgressCondition(),
            ]
        )
        self._log = get_logger("agent_core.loop", config.logging.level)

    def _context(
        self,
        *,
        cycle_index: int,
        projected: float,
        last_result: CycleResult | None,
        prev_unresolved: tuple[str, ...] | None,
    ) -> LoopContext:
        return LoopContext(
            cycle_index=cycle_index,
            config=self._config,
            spent=self._ledger.spent,
            ceiling=self._ledger.ceiling,
            projected_next_cost=projected,
            last_result=last_result,
            prev_unresolved=prev_unresolved,
        )

    def run(self, initial_state: CycleState) -> RunResult:
        state = initial_state
        prev_unresolved = None
        last_outcome = StopOutcome(StopReason.CONTINUE)
        overspent = False
        iterations = 0
        hard_limit = self._config.loop.absolute_max_cycles

        while True:
            # --- controller-level termination backstop (gate-independent) ----
            iterations += 1
            if iterations > hard_limit:
                self._log.error("absolute cycle limit %d hit; aborting", hard_limit)
                last_outcome = StopOutcome(
                    StopReason.ABORTED,
                    detail=f"absolute_max_cycles={hard_limit} exceeded (check gate config)",
                    partial=True,
                )
                break

            projected = self._estimator.project(state)
            admit_ctx = self._context(
                cycle_index=state.cycle_index,
                projected=projected,
                last_result=None,
                prev_unresolved=prev_unresolved,
            )
            denied = self._admission.evaluate(admit_ctx)
            if denied is not None:
                self._log.info("admission stop: %s (%s)", denied.reason.value, denied.detail)
                last_outcome = denied
                break

            # grant a hard allowance = whatever remains under the loop ceiling
            allowance = self._ledger.remaining_for_loop
            cycle_state = state.with_allowance(allowance)
            with debug_span(self._log, "cycle", i=state.cycle_index, allowance=allowance):
                result = self._runner.run(cycle_state)

            try:
                self._ledger.record(result.cost, allowance=allowance)
            except BudgetExceededError as exc:
                # runner ignored its allowance (or estimator lied). Stop hard;
                # reserve stays intact because the over-cost was never recorded.
                self._log.warning("runner exceeded allowance: %s", exc)
                overspent = True
                last_outcome = StopOutcome(StopReason.BUDGET, detail=str(exc), partial=True)
                break

            prev_unresolved = state.unresolved
            state = state.advanced(result)

            outcome_ctx = self._context(
                cycle_index=state.cycle_index,
                projected=0.0,
                last_result=result,
                prev_unresolved=prev_unresolved,
            )
            stopped = self._outcome.evaluate(outcome_ctx)
            if stopped is not None:
                self._log.info("outcome stop: %s (%s)", stopped.reason.value, stopped.detail)
                last_outcome = stopped
                break

        return RunResult(
            reason=last_outcome.reason,
            partial=last_outcome.partial,
            cycles_completed=state.cycle_index - initial_state.cycle_index,
            spent=self._ledger.spent,
            reserve_available=self._ledger.reserve,
            final_state=state,
            detail=last_outcome.detail,
            overspent=overspent,
        )
