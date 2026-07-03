"""Tests for async_loop — differential parity with sync, concurrency via counter."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from agent_core import (
    BudgetExceededError,
    BudgetLedger,
    ConfigError,
    CycleResult,
    CycleState,
    FrameworkConfig,
    LoopController,
    StopReason,
)
from agent_core.async_loop import AsyncLoopController, ParallelClaimRunner
from agent_core.config import AsyncConfig
from agent_core.protocols import AsyncCycleRunner


def _run(coro):
    return asyncio.run(coro)


# ---- Shared estimator -------------------------------------------------------


class FixedEstimator:
    def __init__(self, cost: float = 1.0) -> None:
        self._cost = cost

    def project(self, state: CycleState) -> float:
        return self._cost


# ---- Sync test doubles ------------------------------------------------------


class SyncConverging:
    """Drops one unresolved per cycle, converges (max_conf_delta < eps) on the last."""

    def __init__(self, converge_at: int = 3) -> None:
        self._at = converge_at
        self._n = 0

    def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        if self._n >= self._at:
            return CycleResult(cost=1.0, new_unresolved=(), max_conf_delta=0.01)
        # Drop one claim per cycle so NoProgress never fires before convergence
        return CycleResult(cost=1.0, new_unresolved=state.unresolved[1:], max_conf_delta=0.5)


class SyncStall:
    """Returns the same unresolved set -> triggers NoProgressCondition after cycle 2."""

    def run(self, state: CycleState) -> CycleResult:
        return CycleResult(cost=1.0, new_unresolved=state.unresolved, max_conf_delta=0.5)


class SyncExpensive:
    """High cost; makes nominal progress so NoProgress doesn't fire before BUDGET."""

    def __init__(self, cost: float = 30.0) -> None:
        self._cost = cost
        self._n = 0

    def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        # Change the set each cycle so NoProgress never fires
        return CycleResult(
            cost=self._cost,
            new_unresolved=(f"c{self._n}",),
            max_conf_delta=0.5,
        )


class SyncCap:
    """Cheap, always progresses -> hits max_cycles (CAP)."""

    def __init__(self) -> None:
        self._n = 0

    def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        return CycleResult(cost=0.1, new_unresolved=(f"k{self._n}",), max_conf_delta=0.5)


# ---- Async test doubles (async mirror of sync doubles) ----------------------


class AConverging:
    def __init__(self, at: int = 3) -> None:
        self._at = at
        self._n = 0

    async def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        if self._n >= self._at:
            return CycleResult(cost=1.0, new_unresolved=(), max_conf_delta=0.01)
        return CycleResult(cost=1.0, new_unresolved=state.unresolved[1:], max_conf_delta=0.5)


class AStall:
    async def run(self, state: CycleState) -> CycleResult:
        return CycleResult(cost=1.0, new_unresolved=state.unresolved, max_conf_delta=0.5)


class AExpensive:
    def __init__(self, cost: float = 30.0) -> None:
        self._cost = cost
        self._n = 0

    async def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        return CycleResult(
            cost=self._cost,
            new_unresolved=(f"c{self._n}",),
            max_conf_delta=0.5,
        )


class ACap:
    def __init__(self) -> None:
        self._n = 0

    async def run(self, state: CycleState) -> CycleResult:
        self._n += 1
        return CycleResult(cost=0.1, new_unresolved=(f"k{self._n}",), max_conf_delta=0.5)


# ---- Differential parity tests ----------------------------------------------


@pytest.mark.parametrize(
    "sync_runner,async_runner,expected_reason,cfg_overrides",
    [
        (SyncConverging(3), AConverging(3), StopReason.SUCCESS, {"loop": {"max_cycles": 5}}),
        (SyncStall(), AStall(), StopReason.STALL, {"loop": {"max_cycles": 5}}),
        (
            SyncExpensive(30.0),
            AExpensive(30.0),
            StopReason.BUDGET,
            {"budget": {"cap_units": 100.0, "reserve_fraction": 0.2}},
        ),
        (SyncCap(), ACap(), StopReason.CAP, {"loop": {"max_cycles": 3}}),
    ],
)
def test_async_matches_sync_runresult(
    sync_runner, async_runner, expected_reason, cfg_overrides
) -> None:
    cfg = FrameworkConfig.from_dict(cfg_overrides)
    s0 = CycleState(unresolved=("a", "b", "c"))
    sync = LoopController(cfg, BudgetLedger(cfg), sync_runner, FixedEstimator(1.0)).run(s0)
    asy = _run(
        AsyncLoopController(cfg, BudgetLedger(cfg), async_runner, FixedEstimator(1.0)).run(s0)
    )
    assert (asy.reason, asy.cycles_completed, asy.partial, asy.overspent) == (
        sync.reason,
        sync.cycles_completed,
        sync.partial,
        sync.overspent,
    ), f"sync={sync}, async={asy}"
    assert asy.reason is expected_reason


# ---- Concurrency tests (counter-based, deterministic) -----------------------


def test_parallel_runner_respects_and_uses_max_concurrency() -> None:
    async def run_test() -> int:
        peak: list[int] = [0]
        current: list[int] = [0]
        lock = asyncio.Lock()

        async def verify(claim: str) -> CycleResult:
            async with lock:
                current[0] += 1
                peak[0] = max(peak[0], current[0])
            await asyncio.sleep(0)  # yield to let others start
            async with lock:
                current[0] -= 1
            return CycleResult(cost=0.1, new_unresolved=(), max_conf_delta=0.01)

        state = CycleState(unresolved=tuple(f"c{i}" for i in range(20)))
        await ParallelClaimRunner(AsyncConfig(max_concurrency=3), verify).run(state)
        return peak[0]

    assert _run(run_test()) == 3


def test_parallel_runner_empty_unresolved() -> None:
    async def verify(claim: str) -> CycleResult:
        raise AssertionError("should not be called")  # pragma: no cover

    state = CycleState(unresolved=())
    result = _run(ParallelClaimRunner(AsyncConfig(), verify).run(state))
    assert result.cost == 0.0
    assert result.new_unresolved == ()


def test_invalid_async_config_raises() -> None:
    with pytest.raises(ConfigError, match="max_concurrency"):
        AsyncConfig(max_concurrency=0)


def test_async_config_in_framework_config() -> None:
    cfg = FrameworkConfig.from_dict({"async_exec": {"max_concurrency": 4}})
    assert cfg.async_exec.max_concurrency == 4


def test_old_config_without_async_exec_loads() -> None:
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 3}})
    assert cfg.async_exec == AsyncConfig()  # new section defaulted


def test_async_cycle_runner_protocol_conformance() -> None:
    class MyRunner:
        async def run(self, state: CycleState) -> CycleResult:
            return CycleResult(cost=0.0, new_unresolved=(), max_conf_delta=0.0)

    assert isinstance(MyRunner(), AsyncCycleRunner)


# ---- Admission race: check-then-act guard -----------------------------------


def test_concurrent_admission_cannot_oversubscribe_cap() -> None:
    """record()'s re-validation is the real guard, not the check-then-act race."""
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 100.0, "reserve_fraction": 0.0}})
    ledger = BudgetLedger(cfg)

    async def run_test() -> None:
        async def spend() -> None:
            if ledger.can_admit(60.0):
                await asyncio.sleep(0)
                with contextlib.suppress(BudgetExceededError):
                    ledger.record(60.0, allowance=60.0)

        await asyncio.gather(*(spend() for _ in range(5)))

    _run(run_test())
    assert ledger.spent <= cfg.budget.cap_units


# ---- Overspend path ---------------------------------------------------------


def test_async_runner_overspend_stops_budget() -> None:
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 10.0, "reserve_fraction": 0.0}})
    ledger = BudgetLedger(cfg)

    class GreedyRunner:
        async def run(self, state: CycleState) -> CycleResult:
            return CycleResult(cost=999.0, new_unresolved=(), max_conf_delta=0.5)

    s0 = CycleState(unresolved=("a",))
    result = _run(AsyncLoopController(cfg, ledger, GreedyRunner(), FixedEstimator(1.0)).run(s0))
    assert result.reason is StopReason.BUDGET
    assert result.overspent is True


# ---- Absolute hard limit path -----------------------------------------------


def test_async_absolute_max_cycles_aborts() -> None:
    """ABORTED path: absolute_max_cycles hit when gate conditions never fire."""
    from agent_core.stop import Gate

    # absolute_max_cycles must be >= max_cycles per validation
    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 2, "absolute_max_cycles": 2}})
    ledger = BudgetLedger(cfg)

    class InfiniteRunner:
        async def run(self, state: CycleState) -> CycleResult:
            return CycleResult(cost=0.0, new_unresolved=state.unresolved, max_conf_delta=0.5)

    # Empty gate — no conditions ever stop the loop via normal gates
    admission = Gate([])
    outcome = Gate([])

    s0 = CycleState(unresolved=("a",))
    result = _run(
        AsyncLoopController(
            cfg, ledger, InfiniteRunner(), FixedEstimator(0.0), admission, outcome
        ).run(s0)
    )
    assert result.reason is StopReason.ABORTED
    assert result.partial is True


# ---- Robustness: orphaned task cancellation + duplicate dedup ----------------


def test_parallel_runner_cancels_tasks_on_exception() -> None:
    """If one verify_fn raises, remaining tasks must be cancelled (not left running)."""
    completed: list[str] = []

    async def flaky(claim: str) -> CycleResult:
        if claim == "bad":
            await asyncio.sleep(0)  # yield so c1/c2 start their sleep first
            raise RuntimeError("injected failure")
        await asyncio.sleep(10)  # long sleep — must be cancelled, never completes
        completed.append(claim)
        return CycleResult(cost=0.0, new_unresolved=(), max_conf_delta=0.0)

    state = CycleState(unresolved=("bad", "c1", "c2"))
    with pytest.raises(RuntimeError, match="injected failure"):
        _run(ParallelClaimRunner(AsyncConfig(max_concurrency=3), flaky).run(state))
    assert completed == []


def test_parallel_runner_deduplicates_new_unresolved() -> None:
    """new_unresolved is a set-union: duplicate claim IDs across runners are removed."""

    async def verify(claim: str) -> CycleResult:
        # every runner returns the same shared claim
        return CycleResult(cost=0.0, new_unresolved=("shared",), max_conf_delta=0.0)

    state = CycleState(unresolved=("a", "b", "c"))
    result = _run(ParallelClaimRunner(AsyncConfig(), verify).run(state))
    assert result.new_unresolved == ("shared",)  # deduplicated, not ("shared","shared","shared")


def test_admission_fires_cap_before_hard_limit() -> None:
    """When absolute_max_cycles == max_cycles, the MaxCyclesCondition in the default
    admission gate must emit CAP before the hard-limit backstop emits ABORTED."""

    class ProgressingRunner:
        """Returns a different unresolved set each cycle (avoids NoProgress/STALL)
        but never converges — only MaxCyclesCondition can stop this runner."""

        def __init__(self) -> None:
            self._n = 0

        async def run(self, state: CycleState) -> CycleResult:
            self._n += 1
            return CycleResult(cost=0.0, new_unresolved=(f"c{self._n}",), max_conf_delta=0.5)

    cfg = FrameworkConfig.from_dict({"loop": {"max_cycles": 3, "absolute_max_cycles": 3}})
    result = _run(
        AsyncLoopController(cfg, BudgetLedger(cfg), ProgressingRunner(), FixedEstimator(0.0)).run(
            CycleState(unresolved=("a",))
        )
    )
    assert result.reason is StopReason.CAP
    assert result.cycles_completed == 3
