"""The state-adapter attempt lifecycle, split out of ``engine.py`` to stay under
the size budget (mirrors the ``_reliability_diagnostics`` precedent, Group 0).

``reset -> snapshot(before) -> target.run(item) -> snapshot(after) -> evaluate``,
under the caller's lock (``add-stateful-outcome-evaluation`` Decision C: a
shared adapter instance is not safe under ``max_workers>1`` without one
spanning the whole attempt, target.run() included). A ``reset`` failure raises
``StateResetError`` uncaught -- the caller must not catch it, so it propagates
and aborts the run regardless of ``fail_fast`` (``design.md`` "Failure
semantics"). A ``snapshot``/``evaluate`` failure is wrapped in
``StateSnapshotError``, logged, and returned as a synthetic failing
``ScoreResult`` rather than raised -- the item still gets a normal result,
visibly failed, never silently dropped.
"""

from __future__ import annotations

import logging
import threading

from .interfaces import StateAdapter, StateResetError, StateSnapshotError, TargetRunner
from .types import EvalItem, RunContext, ScoreResult, StateSnapshot, TargetOutput

logger = logging.getLogger(__name__)


def _failed_state_score(reason: str) -> ScoreResult:
    """A synthetic failing score reporting a StateAdapter lifecycle failure.

    Mirrors the engine's existing scorer-error idiom's shape (a visible
    failing ``ScoreResult``, not a swallowed exception) so state failures
    plug into ``EvalEngine._aggregate`` and gate judges via
    ``programmatic_failed`` exactly like any other programmatic failure, with
    no new plumbing.
    """
    return ScoreResult(name="state_lifecycle", value=0.0, passed=False, comment=reason)


def run_state_bracketed_attempt(
    *,
    target: TargetRunner,
    state_adapter: StateAdapter,
    lock: threading.Lock,
    item: EvalItem,
    ctx: RunContext,
) -> tuple[TargetOutput, ScoreResult | None]:
    """Run one attempt bracketed by the state-adapter lifecycle.

    Returns ``(output, state_score)``: ``state_score`` is ``None`` on a clean
    lifecycle (the real ``StateEvaluation``, if produced, is written to
    ``ctx.extra["state_evaluation"]`` for the state scorers to read) or a
    failing score when snapshot/evaluate errored. Raises ``StateResetError``
    — never caught here — when ``reset`` itself fails.
    """
    with lock:
        try:
            state_adapter.reset(ctx)
        except Exception as exc:
            raise StateResetError(f"item {item.id!r}: state reset failed: {exc}") from exc

        state_score: ScoreResult | None = None
        before: StateSnapshot | None
        try:
            before = state_adapter.snapshot(ctx)
        except Exception as exc:
            before = None
            wrapped = StateSnapshotError(f"item {item.id!r}: snapshot(before) failed: {exc}")
            logger.warning(str(wrapped))
            state_score = _failed_state_score(str(wrapped))

        output = target.run(item)

        if before is not None:
            try:
                after = state_adapter.snapshot(ctx)
                ctx.extra["state_evaluation"] = state_adapter.evaluate(item=item, before=before, after=after)
            except Exception as exc:
                wrapped = StateSnapshotError(f"item {item.id!r}: snapshot(after)/evaluate failed: {exc}")
                logger.warning(str(wrapped))
                state_score = _failed_state_score(str(wrapped))

    return output, state_score
