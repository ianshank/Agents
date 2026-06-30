"""agent-core integration adapter for the eval-harness.

Bridges the harness's LLM-judge subsystem to agent-core's deterministic
loop control, allowing :class:`~agent_core.LoopController` to orchestrate
multi-cycle evaluations with budget enforcement and convergence detection.

Claim IDs
---------
``CycleState.unresolved`` holds opaque ``str`` claim IDs.  :class:`ItemStore`
maps those IDs back to :class:`~eval_harness.core.types.EvalItem` objects.
The IDs are never rewritten or sanitised — doing so would corrupt identity
and break ``NoProgressCondition``.

Prerequisites
-------------
Install agent-core from the monorepo before importing this module::

    pip install -e "./agent-core"

All tunables live in :class:`AdapterConfig`; no literals appear in logic.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from eval_harness.core.interfaces import Judge
from eval_harness.core.types import EvalItem, JudgeVerdict

if TYPE_CHECKING:
    from agent_core import BudgetLedger

    from eval_harness.config.models import JudgeBudgetConfig

try:
    from agent_core.protocols import CycleResult, CycleState
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "agent-core is required for eval_harness.agent_core_adapter. "
        "Install it from the monorepo: pip install -e './agent-core'"
    ) from _exc

__all__ = [
    "AdapterConfig",
    "BudgetedJudge",
    "FixedCostEstimator",
    "HarnessJudgeRunner",
    "ItemStore",
    "build_budgeted_judge",
]

log = logging.getLogger(__name__)


class AdapterConfig(BaseModel):
    """Configuration for the agent-core ↔ harness bridge.

    Every tunable is a validated field; no literals appear in logic.
    """

    model_config = ConfigDict(frozen=True)

    resolution_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Judge score >= this value marks a claim as resolved.",
    )
    tokens_per_claim: int = Field(
        default=2_000,
        ge=1,
        description="Estimated token count per judge call (for cost accounting).",
    )
    per_token_rate: float = Field(
        default=1e-5,
        ge=0.0,
        description="Cost per token in agent-core budget units.",
    )
    judge_prompt_template: str = Field(
        default=("Evaluate the following claim.\n\nClaim ID: {claim_id}\nInputs:\n{inputs_json}\nExpected: {expected}"),
        description=("Template for judge prompts. Available variables: {claim_id}, {inputs_json}, {expected}."),
    )


class ItemStore:
    """Maps opaque claim IDs to :class:`~eval_harness.core.types.EvalItem` objects.

    Claim IDs in ``CycleState.unresolved`` are opaque strings.  This store
    is the single bridge from those IDs back to the full ``EvalItem``.
    Duplicate IDs raise :class:`ValueError` at construction time.
    """

    def __init__(self, items: list[EvalItem]) -> None:
        self._store: dict[str, EvalItem] = {}
        for item in items:
            if item.id in self._store:
                raise ValueError(f"Duplicate EvalItem ID: {item.id!r}")
            self._store[item.id] = item

    @property
    def claim_ids(self) -> tuple[str, ...]:
        """All stored IDs in insertion order — pass to ``CycleState.unresolved``."""
        return tuple(self._store.keys())

    def get(self, claim_id: str) -> EvalItem:
        try:
            return self._store[claim_id]
        except KeyError:
            raise KeyError(f"No EvalItem with ID {claim_id!r}") from None

    def __len__(self) -> int:
        return len(self._store)


class HarnessJudgeRunner:
    """Implements the agent-core ``CycleRunner`` protocol via the harness :class:`Judge`.

    Each :meth:`run` call evaluates every unresolved claim with the injected
    judge.  Claims scoring ``>= config.resolution_threshold`` are resolved and
    dropped from the next cycle's ``unresolved`` set.

    Cost per cycle: ``len(unresolved) * tokens_per_claim * per_token_rate``.

    ``max_conf_delta`` tracks the largest score change since the previous cycle.
    On the first cycle ``prev_score`` defaults to ``0.0`` so delta equals the
    raw score — this prevents a spurious convergence signal on cycle 1.

    Create a new instance per ``LoopController`` run (state is not reset between
    ``run`` calls; the controller owns the lifecycle).
    """

    def __init__(
        self,
        judge: Judge,
        item_store: ItemStore,
        config: AdapterConfig,
    ) -> None:
        self._judge = judge
        self._store = item_store
        self._config = config
        self._prev_scores: dict[str, float] = {}

    def run(self, state: CycleState) -> CycleResult:
        scores: dict[str, float] = {}
        still_unresolved: list[str] = []
        total_cost = 0.0

        for claim_id in state.unresolved:
            item = self._store.get(claim_id)
            prompt = self._config.judge_prompt_template.format(
                claim_id=claim_id,
                inputs_json=json.dumps(item.inputs, ensure_ascii=False, indent=2),
                expected=item.expected,
            )
            verdict = self._judge.evaluate(prompt, context={"claim_id": claim_id})
            score = verdict.score
            scores[claim_id] = score
            total_cost += self._config.tokens_per_claim * self._config.per_token_rate

            resolved = score >= self._config.resolution_threshold
            if not resolved:
                still_unresolved.append(claim_id)

            log.debug(
                "cycle=%d claim=%r score=%.4f resolved=%s",
                state.cycle_index,
                claim_id,
                score,
                resolved,
            )

        # prev defaults to 0.0 so first-cycle delta == score (no premature convergence)
        max_delta = max(
            (abs(s - self._prev_scores.get(cid, 0.0)) for cid, s in scores.items()),
            default=0.0,
        )
        self._prev_scores = scores

        new_evidence = len(still_unresolved) < len(state.unresolved)

        return CycleResult(
            cost=total_cost,
            new_unresolved=tuple(still_unresolved),
            max_conf_delta=max_delta,
            new_evidence=new_evidence,
        )


class FixedCostEstimator:
    """Implements the agent-core ``CostEstimator`` protocol.

    Projects the next cycle's cost as::

        len(state.unresolved) * config.tokens_per_claim * config.per_token_rate

    All constants come from :class:`AdapterConfig`; nothing is hard-coded.
    """

    def __init__(self, config: AdapterConfig) -> None:
        self._config = config

    def project(self, state: CycleState) -> float:
        return len(state.unresolved) * self._config.tokens_per_claim * self._config.per_token_rate


class _SlidingWindowLimiter:
    """A deterministic sliding-window rate limiter (F-030).

    Admits at most ``max_per_window`` events per ``window_seconds``. Time is read
    from an injected ``clock`` and waiting goes through an injected ``sleeper`` so
    the whole thing is testable without real time. Not internally locked — the
    caller (``BudgetedJudge``) already serialises access under its own lock.
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

    def try_acquire(self) -> bool:
        """Non-blocking: record and return True if a slot is free, else False."""
        now = self._clock()
        self._evict(now)
        if len(self._events) >= self._max:
            return False
        self._events.append(now)
        return True

    def acquire_blocking(self) -> None:
        """Block (via the injected sleeper) until a slot frees, then record it."""
        while True:
            now = self._clock()
            self._evict(now)
            if len(self._events) < self._max:
                self._events.append(now)
                return
            # _evict removed every event at/under (now - window), so the oldest
            # survivor is strictly inside the window and wait is always > 0.
            wait = self._events[0] + self._window - now
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

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        from agent_core import BudgetExceededError

        with self._lock:
            # Rate limit first (F-030), then the cumulative cost cap (F-022). Both
            # run under the lock so window bookkeeping and the reservation stay
            # consistent under parallel execution; the inner call runs outside it.
            if self._limiter is not None:
                if self._on_rate_limited == "skip":
                    if not self._limiter.try_acquire():
                        return JudgeVerdict(score=self._skip_score, reasoning="judge rate limit exceeded (skipped)")
                else:  # block until a slot frees
                    self._limiter.acquire_blocking()
            try:
                self._ledger.record(self._cost_per_call)
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
    """
    from agent_core import BudgetConfig, BudgetLedger, FrameworkConfig

    if budget.cap is None:
        raise ValueError("JudgeBudgetConfig.cap must be set (> 0) when the judge budget is enabled")
    ledger = BudgetLedger(FrameworkConfig(budget=BudgetConfig(cap_units=float(budget.cap), reserve_fraction=0.0)))

    limiter: _SlidingWindowLimiter | None = None
    if budget.max_per_window is not None and budget.window_seconds is not None:
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
