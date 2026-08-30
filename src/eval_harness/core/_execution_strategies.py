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

from .interfaces import StateResetError
from .types import EvalItem, ItemResult, RunContext

logger = logging.getLogger(__name__)


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

        for future in futures:
            try:
                index, result_or_exc = future.result()
            except StateResetError:
                # Never fail_fast-gated -- continuing risks scoring against dirty state.
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            if isinstance(result_or_exc, Exception):
                if first_error is None:
                    first_error = result_or_exc
                if fail_fast:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
            else:
                collected.append((index, result_or_exc))

    if first_error is not None and fail_fast:
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
            results.append(run_one(item, ctx, attempt_index=attempt, item_run_id=item_run_id))
    return results
