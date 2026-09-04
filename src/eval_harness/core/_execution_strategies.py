"""Item execution strategies, split out of ``engine.py`` (behavior-preserving,
no logic change) to stay under the 500-line size budget.

Pure -- takes explicit leaf parameters only (never ``self``, ``EvalConfig``,
or ``EvalEngine``). ``core`` has no declared dependencies in
``architecture.yaml``; importing ``EvalConfig``/``EvalEngine`` here -- even
only under ``TYPE_CHECKING`` -- would create an undeclared edge and fail the
architecture-drift gate. Per-item ``RunContext`` construction is delegated to
an injected ``make_ctx`` callable built by the thin wrapper methods that stay
on ``EvalEngine`` (which already legitimately imports ``EvalConfig``).
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial

from ._imports import DisallowedImportError
from .interfaces import StateResetError
from .types import EvalItem, ItemResult, RunContext, ScoreResult, TargetOutput

logger = logging.getLogger(__name__)

#: Failures that abort the whole run regardless of ``item_error_policy``,
#: because they are not item outcomes and recording them per item would be
#: misleading rather than informative.
#:
#: * ``StateResetError`` -- continuing risks scoring against dirty state.
#: * ``DisallowedImportError`` -- the target could not be resolved at all, so
#:   every item would fail identically. That is a configuration or trust
#:   decision, not N independent measurements, and a run that "completed" with
#:   everything failed is exactly the kind of misleading artefact this module
#:   now exists to prevent.
FATAL_RUN_ERRORS: tuple[type[BaseException], ...] = (StateResetError, DisallowedImportError)

#: Score name carried by an item whose target raised. A structural identifier,
#: not a tuning knob, so it is a module constant rather than a config field --
#: mirroring ``_state_lifecycle``'s ``"state_lifecycle"`` score. Tests and gate
#: rules address the score by this name, so it is exported rather than inlined.
ITEM_ERROR_SCORE_NAME = "item_execution"

#: ``RunSettings.item_error_policy`` values. Named here so no execution path
#: compares against a bare string literal; the schema itself is declared as a
#: ``Literal`` on the config field, which stays the single source of truth.
ITEM_ERROR_POLICY_RECORD = "record"
ITEM_ERROR_POLICY_RAISE = "raise"


def build_failed_item_result(
    item: EvalItem,
    exc: BaseException,
    *,
    error_score: float,
    attempt_index: int | None = None,
    item_run_id: str | None = None,
) -> ItemResult:
    """Render a target failure as a normal, visibly-failed :class:`ItemResult`.

    The harness already had a data model for this -- ``TargetOutput.error`` is
    serialized by ``RunResult._item_to_dict`` -- and already had the idiom, in
    ``_state_lifecycle._failed_state_score``. This is that idiom applied to the
    one failure mode that previously escaped it, so a failed item reaches sinks
    and aggregates like any other rather than disappearing from the run.

    ``error_score`` comes from ``RunSettings.item_error_score``; nothing here
    defaults it, so the config field remains the only place the value is
    declared.
    """
    return ItemResult(
        item=item,
        output=TargetOutput(output=None, error=str(exc)),
        scores=[
            ScoreResult(
                name=ITEM_ERROR_SCORE_NAME,
                value=error_score,
                passed=False,
                comment=f"target error: {exc}",
            )
        ],
        attempt_index=attempt_index,
        attempt_id=f"{item.id}:{attempt_index}" if attempt_index is not None else None,
        item_run_id=item_run_id,
    )


def run_item_guarded(
    call: Callable[[], ItemResult],
    item: EvalItem,
    *,
    item_error_policy: str,
    item_error_score: float,
    attempt_index: int | None = None,
    item_run_id: str | None = None,
) -> ItemResult:
    """Run one attempt, applying ``item_error_policy`` to a target failure.

    Shared by both sequential paths so they cannot drift from the parallel one.
    Every member of ``FATAL_RUN_ERRORS`` is re-raised untouched under every
    policy -- see that constant for why each one aborts the run rather than
    becoming a recorded item failure.

    ``call`` is a zero-argument closure rather than a runner plus arguments, so
    each caller keeps its own exact invocation -- notably the legacy two-argument
    ``_run_one(item, ctx)`` form, which a test double may still be bound to.
    """
    try:
        return call()
    except FATAL_RUN_ERRORS:
        raise
    except Exception as exc:
        if item_error_policy == ITEM_ERROR_POLICY_RAISE:
            raise
        logger.error(
            "Item %s failed: %s -- recording a failed result (item_error_policy=%r)",
            item.id,
            exc,
            item_error_policy,
        )
        return build_failed_item_result(
            item,
            exc,
            error_score=item_error_score,
            attempt_index=attempt_index,
            item_run_id=item_run_id,
        )


def _make_item_rng(base_seed: int, item_index: int) -> random.Random:
    """Create a deterministic per-item RNG.

    Each item receives ``Random(base_seed + item_index)`` so the random stream
    is identical regardless of thread scheduling.
    """
    return random.Random(base_seed + item_index)


def _execute_parallel(
    items: list[EvalItem],
    run_id: str,
    *,
    max_workers: int,
    base_seed: int,
    repetitions: int,
    fail_fast: bool,
    make_ctx: Callable[[int, random.Random], RunContext],
    run_one_safe: Callable[..., tuple[int, ItemResult | Exception]],
    item_error_policy: str,
    item_error_score: float,
) -> list[ItemResult]:
    """Execute items -- and, when ``repetitions > 1``, each item's attempts --
    in parallel via ``ThreadPoolExecutor``.

    Every ``(item, attempt)`` pair gets its own submission and its own
    ``RunContext`` (built by ``make_ctx``), RNG freshly seeded from
    ``base_seed + item_index`` -- never advanced across attempts of the same
    item, only ever re-derived from this loop's own ``enumerate()`` index (not
    ``ctx.item_index``, which nothing reads back). At ``repetitions == 1`` this
    submits exactly one future per item with ``attempt_index=None``, identical
    to the pre-reliability-metrics engine. Results are collected in submission
    order -- item-major, attempts ascending within an item. On ``fail_fast``,
    the executor is shut down immediately.

    ``item_error_policy`` is the *effective* policy (the engine has already
    folded ``fail_fast`` into it), and it -- never ``max_workers`` -- decides
    what a target failure means. Under ``record`` a failed attempt is collected
    as a visibly-failed ``ItemResult`` at its own submission index, so it keeps
    its place in the ordering and its weight in every aggregate. This path used
    to drop it, which silently shrank the denominator and inflated ``pass_rate``.
    """
    logger.info(
        "Parallel execution: %d items x %d repetitions with max_workers=%d",
        len(items),
        repetitions,
        max_workers,
    )

    collected: list[tuple[int, ItemResult]] = []
    first_error: Exception | None = None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: list[Future[tuple[int, ItemResult | Exception]]] = []
        # Submission identity, positionally aligned with ``futures``. A future
        # reports only its item index, but rendering a failed attempt needs the
        # item itself and its attempt identity, and neither is recoverable from
        # the index alone once ``repetitions > 1`` fans one index into many.
        submitted: list[tuple[EvalItem, int | None, str | None]] = []
        for idx, item in enumerate(items):
            item_run_id = f"{run_id}:{item.id}" if repetitions > 1 else None
            for attempt in range(repetitions):
                attempt_index = attempt if repetitions > 1 else None
                item_rng = _make_item_rng(base_seed, idx)
                ctx = make_ctx(idx, item_rng)
                futures.append(
                    executor.submit(
                        run_one_safe,
                        idx,
                        item,
                        ctx,
                        attempt_index=attempt_index,
                        item_run_id=item_run_id,
                    )
                )
                submitted.append((item, attempt_index, item_run_id))

        for future, (item, attempt_index, item_run_id) in zip(futures, submitted, strict=True):
            try:
                index, result_or_exc = future.result()
            except FATAL_RUN_ERRORS:
                # Never policy-gated: see FATAL_RUN_ERRORS for why each member
                # aborts the run rather than becoming a recorded item failure.
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            if isinstance(result_or_exc, Exception):
                if first_error is None:
                    first_error = result_or_exc
                if fail_fast:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                if item_error_policy == ITEM_ERROR_POLICY_RECORD:
                    collected.append(
                        (
                            index,
                            build_failed_item_result(
                                item,
                                result_or_exc,
                                error_score=item_error_score,
                                attempt_index=attempt_index,
                                item_run_id=item_run_id,
                            ),
                        )
                    )
            else:
                collected.append((index, result_or_exc))

    # ``fail_fast`` has already been folded into the effective policy by the
    # caller, so this single condition covers both aborts.
    if first_error is not None and item_error_policy == ITEM_ERROR_POLICY_RAISE:
        raise first_error

    # Sort by submission index to guarantee deterministic ordering
    collected.sort(key=lambda pair: pair[0])
    return [result for _, result in collected]


def _execute_sequential_repeated(
    items: list[EvalItem],
    run_id: str,
    *,
    base_seed: int,
    repetitions: int,
    make_ctx: Callable[[int, random.Random], RunContext],
    run_one: Callable[..., ItemResult],
    item_error_policy: str,
    item_error_score: float,
) -> list[ItemResult]:
    """Execute items sequentially with ``repetitions > 1``.

    The single-attempt sequential path (``EvalEngine.run``) threads one
    shared, continuously-advancing RNG across every item -- the original
    engine behaviour, preserved unchanged for ``repetitions == 1`` (that path
    never calls this function). Here, each attempt instead gets its own RNG
    freshly constructed from ``base_seed + item_index`` -- the same per-item
    seed every attempt, never advanced between attempts of that item -- so a
    scorer that draws from ``ctx.rng`` cannot manufacture cross-attempt
    flakiness from RNG drift alone (see design.md "Seeding -- and why it is
    not the lever"). Seeds are derived from this loop's own ``enumerate()``
    index, never ``ctx.item_index`` (which the single-attempt sequential path
    never sets, and nothing reads).
    """
    results: list[ItemResult] = []
    for idx, item in enumerate(items):
        item_run_id = f"{run_id}:{item.id}"
        for attempt in range(repetitions):
            ctx = make_ctx(idx, _make_item_rng(base_seed, idx))
            results.append(
                run_item_guarded(
                    partial(run_one, item, ctx, attempt_index=attempt, item_run_id=item_run_id),
                    item,
                    item_error_policy=item_error_policy,
                    item_error_score=item_error_score,
                    attempt_index=attempt,
                    item_run_id=item_run_id,
                )
            )
    return results
