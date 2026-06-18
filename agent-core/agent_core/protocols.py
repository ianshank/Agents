"""Extension seams.

These Protocols are the contract between the deterministic core and the
I/O-bound nodes (verifier, retrieval, cost model). The core depends only on
these abstractions, so real implementations — or test doubles — can be injected
without touching control logic. This is the modular/backwards-compatible spine:
add or swap an implementation, never edit the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid runtime import cycle; restores static typing
    from .config import FrameworkConfig

ClaimId = str


@dataclass(frozen=True)
class CycleState:
    """Immutable snapshot passed into each cycle.

    ``allowance`` is the hard spend authorization for this cycle. A well-behaved
    CycleRunner MUST NOT incur cost beyond it; the ledger enforces this on record.
    Default is unbounded for backwards compatibility, but the controller always
    sets a finite allowance derived from the remaining loop budget.
    """

    cycle_index: int = 1
    unresolved: tuple[ClaimId, ...] = ()
    # last observed max per-claim confidence delta; None before any cycle runs
    last_max_conf_delta: float | None = None
    allowance: float = float("inf")

    def advanced(self, result: CycleResult) -> CycleState:
        return replace(
            self,
            cycle_index=self.cycle_index + 1,
            unresolved=result.new_unresolved,
            last_max_conf_delta=result.max_conf_delta,
        )

    def with_allowance(self, allowance: float) -> CycleState:
        return replace(self, allowance=allowance)


@dataclass(frozen=True)
class CycleResult:
    """What a CycleRunner reports after one verification pass."""

    cost: float
    new_unresolved: tuple[ClaimId, ...]
    max_conf_delta: float
    new_evidence: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if self.cost < 0:
            raise ValueError("CycleResult.cost must be >= 0")


@runtime_checkable
class CycleRunner(Protocol):
    """Runs a single verification cycle. Real impl wraps the adversarial verifier."""

    def run(self, state: CycleState) -> CycleResult: ...


@runtime_checkable
class CostEstimator(Protocol):
    """Projects the cost of the *next* cycle for the admission gate."""

    def project(self, state: CycleState) -> float: ...


class StopReason(str, Enum):
    CONTINUE = "continue"
    SUCCESS = "success"  # converged
    STALL = "stall"  # no progress
    BUDGET = "budget"  # admission denied on cost, or runner exceeded allowance
    CAP = "cap"  # admission denied on cycle count
    ABORTED = "aborted"  # controller hard safety limit hit (gate misconfiguration)


@dataclass(frozen=True)
class StopOutcome:
    reason: StopReason
    detail: str = ""
    partial: bool = False


@dataclass(frozen=True)
class LoopContext:
    """Everything a stop condition might need to make its decision."""

    cycle_index: int
    config: FrameworkConfig
    spent: float = 0.0
    ceiling: float = 0.0
    projected_next_cost: float = 0.0
    last_result: CycleResult | None = None
    prev_unresolved: tuple[ClaimId, ...] | None = None
    extras: dict = field(default_factory=dict)


@runtime_checkable
class StopCondition(Protocol):
    """Returns a StopOutcome to halt, or None to let evaluation continue."""

    def evaluate(self, ctx: LoopContext) -> StopOutcome | None: ...
