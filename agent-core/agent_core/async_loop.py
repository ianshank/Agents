"""Async / parallel cycle execution.

AsyncLoopController mirrors the sync LoopController control flow with await.
ParallelClaimRunner fans out per-claim async callables under a concurrency cap.

IMPORTANT: loop.py is NOT modified. This module duplicates the ~40-line
control flow rather than extracting shared helpers — the sync core is a tight
imperative while/break over live ledger state; shared helpers would introduce
regression risk on lightly-tested control logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from .budget import BudgetExceededError, BudgetLedger
from .config import AsyncConfig, FrameworkConfig
from .logging_util import debug_span, get_logger
from .loop import RunResult
from .protocols import (
    AsyncCycleRunner,
    ClaimId,
    CostEstimator,
    CycleResult,
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


class AsyncLoopController:
    """Async mirror of LoopController — duplicates control flow, reuses data types."""

    def __init__(
        self,
        config: FrameworkConfig,
        ledger: BudgetLedger,
        runner: AsyncCycleRunner,
        estimator: CostEstimator,
        admission_gate: Gate | None = None,
        outcome_check: Gate | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._runner = runner
        self._estimator = estimator
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
        self._log = get_logger("agent_core.async_loop", config.logging.level)

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

    async def run(self, initial_state: CycleState) -> RunResult:
        state = initial_state
        prev_unresolved: tuple[ClaimId, ...] | None = None
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
                result = await self._runner.run(cycle_state)

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


# Type alias for the per-claim async verify callable
ClaimVerifier = Callable[[ClaimId], Coroutine[Any, Any, CycleResult]]


class ParallelClaimRunner:
    """Fans out per-claim async verify callables under a semaphore-enforced concurrency cap.

    The verify_fn takes a single ClaimId and returns a CycleResult.
    Aggregated CycleResult: cost=sum, max_conf_delta=max, new_unresolved=union,
    new_evidence=any.
    """

    def __init__(
        self,
        config: AsyncConfig,
        verify_fn: ClaimVerifier,
    ) -> None:
        self._config = config
        self._verify_fn = verify_fn

    async def run(self, state: CycleState) -> CycleResult:
        if not state.unresolved:
            # Guard: max() of empty sequence would raise
            return CycleResult(cost=0.0, new_unresolved=(), max_conf_delta=0.0)

        sem = asyncio.Semaphore(self._config.max_concurrency)

        async def bounded_verify(claim: ClaimId) -> CycleResult:
            async with sem:
                return await self._verify_fn(claim)

        tasks: list[asyncio.Task[CycleResult]] = [
            asyncio.create_task(bounded_verify(c)) for c in state.unresolved
        ]
        results: list[CycleResult] = await asyncio.gather(*tasks)

        total_cost = sum(r.cost for r in results)
        max_conf_delta = max(r.max_conf_delta for r in results)  # safe: results non-empty
        # union of unresolved across all claim results
        new_unresolved: tuple[ClaimId, ...] = tuple(c for r in results for c in r.new_unresolved)
        new_evidence = any(r.new_evidence for r in results)

        return CycleResult(
            cost=total_cost,
            new_unresolved=new_unresolved,
            max_conf_delta=max_conf_delta,
            new_evidence=new_evidence,
        )
