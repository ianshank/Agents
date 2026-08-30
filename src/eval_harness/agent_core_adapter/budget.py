"""Judge cost caps (F-022) and sliding-window rate limiting (F-030).

Split from ``agent_core_adapter/__init__.py`` purely to stay under the
500-line file budget (see ``calibration.py``'s module docstring for the
sibling-module precedent this package already established). ``agent_core``
is imported lazily throughout -- inside ``TYPE_CHECKING`` for annotations and
inside function bodies for runtime use -- so the offline path never pulls it
in unless judge budgeting is actually enabled.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from eval_harness.core.interfaces import Judge
from eval_harness.core.types import JudgeVerdict

if TYPE_CHECKING:
    from agent_core import BudgetLedger

    from eval_harness.config.models import JudgeBudgetConfig


class _SlidingWindowLimiter:
    """A deterministic sliding-window rate limiter (F-030).

    Admits at most ``max_per_window`` events per ``window_seconds``. Time is read
    from an injected ``clock`` and waiting goes through an injected ``sleeper`` so
    the whole thing is testable without real time. Not internally locked — the
    caller (``BudgetedJudge``) already serialises access under its own lock.

    Acquisition is N-at-a-time (``try_acquire_n`` / ``acquire_blocking_n``, N
    defaulting to 1) so a caller whose one logical call actually costs N provider
    calls — e.g. a ``BudgetedJudge`` wrapping an N-member panel — reserves all N
    atomically: check-then-reserve-all-or-none, never a partial reservation, since
    there is no "release" to unwind one if a later slot in the same batch turned
    out to be unavailable.
    """

    def __init__(
        self,
        max_per_window: int,
        window_seconds: float,
        *,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> None:
        self._max = int(max_per_window)
        self._window = float(window_seconds)
        self._clock = clock
        self._sleeper = sleeper
        self._events: deque[float] = deque()

    def _evict(self, now: float) -> None:
        boundary = now - self._window
        while self._events and self._events[0] <= boundary:
            self._events.popleft()

    def try_acquire_n(self, n: int = 1) -> bool:
        """Non-blocking, atomic: record all ``n`` and return True, or record none and return False."""
        now = self._clock()
        self._evict(now)
        if len(self._events) + n > self._max:
            return False
        for _ in range(n):
            self._events.append(now)
        return True

    def acquire_blocking_n(self, n: int = 1) -> None:
        """Block (via the injected sleeper) until ``n`` slots are simultaneously free.

        Waits for all ``n`` at once rather than one at a time: freeing only the single
        oldest event is not enough room for ``n > 1``, and one-at-a-time acquisition
        across separate lock releases would not be atomic against another caller.
        """
        if n > self._max:
            raise ValueError(f"cannot acquire {n} slot(s): window capacity is only {self._max}")
        while True:
            now = self._clock()
            self._evict(now)
            if len(self._events) + n <= self._max:
                for _ in range(n):
                    self._events.append(now)
                return
            # The oldest `deficit` events must age out before n more fit; _evict already
            # removed everything at/under (now - window), so this wait is always > 0.
            deficit = len(self._events) + n - self._max
            wait = self._events[deficit - 1] + self._window - now
            self._sleeper(wait)


class BudgetedJudge(Judge):
    """Wraps a :class:`Judge` with a cumulative per-run cost cap (F-022).

    Each :meth:`evaluate` **reserves** ``cost_per_call`` against an injected
    ``agent_core.BudgetLedger`` *before* delegating to the inner judge. The
    reservation happens under a lock, so under parallel item execution the cap is
    never overshot and no in-flight call is retroactively rejected — the inner
    judge call itself runs outside the lock and still parallelises. When the cap
    is exhausted the wrapper either re-raises ``BudgetExceededError`` or returns a
    sentinel verdict, per ``on_exceeded``.

    The cumulative cap can be paired with an **optional** time-windowed rate limit
    (F-030): when a ``limiter`` is supplied, each call is gated by the sliding
    window *before* the cost reservation — blocking until a slot frees
    (``on_rate_limited='block'``) or returning a sentinel verdict
    (``on_rate_limited='skip'``). The cap and the window are independent. ``ledger``
    is built with ``reserve_fraction=0`` by :func:`build_budgeted_judge` so the
    configured cap maps 1:1 to spendable units. All tunables are injected; nothing
    is hard-coded.

    ``inner`` may itself make more than one provider call per :meth:`evaluate` (a
    ``PanelJudge`` evaluating N members). Read duck-typed off ``inner.calls_per_evaluate``
    (default 1), that multiplier scales *both* the cost reservation and the rate-limit
    slot consumption, so a cap/window sized for one provider call reserves N — never
    silently under-charging by a factor of N. Re-exposed as ``self.calls_per_evaluate``
    so a ``BudgetedJudge`` wrapping another duck-typed-reading wrapper still reports its
    true multiplier upward.
    """

    def __init__(
        self,
        inner: Judge,
        ledger: BudgetLedger,
        cost_per_call: float,
        on_exceeded: str = "raise",
        skip_score: float = 0.0,
        limiter: _SlidingWindowLimiter | None = None,
        on_rate_limited: str = "block",
    ) -> None:
        if on_exceeded not in ("raise", "skip"):
            raise ValueError("on_exceeded must be 'raise' or 'skip'")
        if on_rate_limited not in ("block", "skip"):
            raise ValueError("on_rate_limited must be 'block' or 'skip'")
        self._inner = inner
        self._ledger = ledger
        self._cost_per_call = float(cost_per_call)
        self._on_exceeded = on_exceeded
        # Sentinel verdict score when the budget is exhausted and on_exceeded='skip'.
        # Defaults to the same 0.0 fail-safe the OpenAI/Anthropic judges use for an
        # unparseable response; overridable via JudgeBudgetConfig.skip_score.
        self._skip_score = float(skip_score)
        self._limiter = limiter
        self._on_rate_limited = on_rate_limited
        self._lock = threading.Lock()
        self.calls_per_evaluate = int(getattr(inner, "calls_per_evaluate", 1))

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        from agent_core import BudgetExceededError

        with self._lock:
            # Rate limit first (F-030), then the cumulative cost cap (F-022). Both
            # run under the lock so window bookkeeping and the reservation stay
            # consistent under parallel execution; the inner call runs outside it.
            # Both are charged calls_per_evaluate units so a panel-of-N under this
            # wrapper reserves N, not 1.
            if self._limiter is not None:
                if self._on_rate_limited == "skip":
                    if not self._limiter.try_acquire_n(self.calls_per_evaluate):
                        return JudgeVerdict(score=self._skip_score, reasoning="judge rate limit exceeded (skipped)")
                else:  # block until all needed slots free
                    self._limiter.acquire_blocking_n(self.calls_per_evaluate)
            try:
                self._ledger.record(self._cost_per_call * self.calls_per_evaluate)
            except BudgetExceededError:
                if self._on_exceeded == "skip":
                    return JudgeVerdict(score=self._skip_score, reasoning="judge budget exhausted (skipped)")
                raise
        # Budget reserved; call outside the lock so judge calls still parallelise.
        return self._inner.evaluate(prompt, context)

    def attach_client(self, client: object) -> None:
        """Delegate client attachment to the inner judge if it supports it."""
        attach = getattr(self._inner, "attach_client", None)
        if callable(attach):
            attach(client)


def _reject_if_calls_exceed_window(inner: Judge, calls_per_evaluate: int, max_per_window: int) -> None:
    """Fail fast at construction: no amount of waiting grows ``max_per_window``."""
    if calls_per_evaluate > max_per_window:
        raise ValueError(
            f"{type(inner).__name__} makes {calls_per_evaluate} call(s) per evaluate(), which "
            f"exceeds max_per_window={max_per_window}; raise max_per_window to at least "
            f"{calls_per_evaluate} or reduce the number of panel members"
        )


def build_budgeted_judge(
    inner: Judge,
    budget: JudgeBudgetConfig,
    *,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Judge:
    """Wrap ``inner`` in a :class:`BudgetedJudge` from a ``JudgeBudgetConfig``.

    Imports agent_core lazily so the offline path never pulls it in when budgeting
    is disabled. ``budget`` must have ``cap`` (> 0), ``cost_per_call`` and
    ``on_exceeded`` attributes (an ``eval_harness.config.models.JudgeBudgetConfig``).
    The ledger is constructed with ``reserve_fraction=0`` so the cap is fully
    spendable, and spend is recorded against the cap.

    When ``budget.max_per_window`` / ``window_seconds`` are set, a sliding-window
    rate limiter (F-030) is also attached. ``clock``/``sleeper`` are injectable for
    determinism in tests and default to ``time.monotonic`` / ``time.sleep``.

    ``inner.calls_per_evaluate`` (duck-typed, default 1) is validated against
    ``max_per_window`` here too — see :func:`_reject_if_calls_exceed_window`.
    """
    from agent_core import BudgetConfig, BudgetLedger, FrameworkConfig

    if budget.cap is None:
        raise ValueError("JudgeBudgetConfig.cap must be set (> 0) when the judge budget is enabled")
    ledger = BudgetLedger(FrameworkConfig(budget=BudgetConfig(cap_units=float(budget.cap), reserve_fraction=0.0)))

    calls_per_evaluate = int(getattr(inner, "calls_per_evaluate", 1))

    limiter: _SlidingWindowLimiter | None = None
    if budget.max_per_window is not None and budget.window_seconds is not None:
        _reject_if_calls_exceed_window(inner, calls_per_evaluate, budget.max_per_window)
        limiter = _SlidingWindowLimiter(
            budget.max_per_window,
            budget.window_seconds,
            clock=clock or time.monotonic,
            sleeper=sleeper or time.sleep,
        )

    return BudgetedJudge(
        inner,
        ledger,
        cost_per_call=budget.cost_per_call,
        on_exceeded=budget.on_exceeded,
        skip_score=budget.skip_score,
        limiter=limiter,
        on_rate_limited=budget.on_rate_limited,
    )
