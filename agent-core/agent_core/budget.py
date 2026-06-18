"""Per-run cost budget ledger.

Owns all budget arithmetic: the report reserve, the loop spend ceiling, the
running total, and the admission test ``can_admit``. No threshold is hardcoded;
everything derives from the injected :class:`FrameworkConfig`.

Hard guarantees (enforced, not assumed):
  * ``record`` rejects a cost that exceeds the per-cycle ``allowance`` it was
    granted — a runner that overspends raises ``BudgetExceededError`` instead of
    silently breaching the budget.
  * cumulative ``spent`` can never exceed ``cap``.
The ledger is thread-safe so parallel cycle execution cannot corrupt the total.
"""

from __future__ import annotations

import threading

from .config import FrameworkConfig
from .logging_util import get_logger

_EPS = 1e-9  # float tolerance for boundary comparisons


class BudgetExceededError(RuntimeError):
    """Raised when a recorded cost would breach its allowance or the hard cap."""


class BudgetLedger:
    def __init__(self, config: FrameworkConfig) -> None:
        self._config = config
        self._cap = config.budget.cap_units
        self._reserve = config.reserve_units
        self._ceiling = config.loop_ceiling_units
        self._spent = 0.0
        self._lock = threading.Lock()
        self._log = get_logger("agent_core.budget", config.logging.level)

    # --- read-only views -----------------------------------------------------
    @property
    def cap(self) -> float:
        return self._cap

    @property
    def reserve(self) -> float:
        return self._reserve

    @property
    def ceiling(self) -> float:
        return self._ceiling

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def remaining_for_loop(self) -> float:
        with self._lock:
            return max(0.0, self._ceiling - self._spent)

    # --- operations ----------------------------------------------------------
    def can_admit(self, projected_cost: float) -> bool:
        """True if a cycle projected to cost ``projected_cost`` fits under the ceiling."""
        if projected_cost < 0:
            raise ValueError("projected_cost must be >= 0")
        with self._lock:
            ok = (self._spent + projected_cost) <= self._ceiling + _EPS
            spent = self._spent
        if not ok:
            self._log.info(
                "admission denied: spent=%.1f + projected=%.1f > ceiling=%.1f",
                spent,
                projected_cost,
                self._ceiling,
            )
        return ok

    def record(self, cost: float, *, allowance: float = float("inf")) -> float:
        """Record actual spend; returns the new total.

        Raises BudgetExceededError if ``cost`` exceeds the granted ``allowance`` or
        if the cumulative total would exceed the hard ``cap``. Spend is NOT applied
        when it would breach — the ledger stays consistent for the caller to finalise.
        """
        if cost < 0:
            raise ValueError("cost must be >= 0")
        with self._lock:
            if cost > allowance + _EPS:
                raise BudgetExceededError(
                    f"cycle cost {cost:.1f} exceeds allowance {allowance:.1f}"
                )
            if (self._spent + cost) > self._cap + _EPS:
                raise BudgetExceededError(
                    f"recording {cost:.1f} would breach cap "
                    f"(spent={self._spent:.1f}, cap={self._cap:.1f})"
                )
            self._spent += cost
            new_total = self._spent
        self._log.debug("recorded cost=%.1f total=%.1f", cost, new_total)
        return new_total
