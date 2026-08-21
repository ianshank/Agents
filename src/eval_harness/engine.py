"""The evaluation engine: orchestrates load -> run -> score -> aggregate -> emit.

The engine holds no behavioural literals. Seed, sampling, component selection
and parameters all come from the validated config; the clock and RNG are
injectable so runs are fully deterministic under test.
"""

from __future__ import annotations

import logging
import random
import statistics
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, cast

from .config.models import EvalConfig
from .core._reliability_diagnostics import _reliability_diagnostics
from .core._state_lifecycle import run_state_bracketed_attempt
from .core.interfaces import (
    DatasetSource,
    Judge,
    ResultSink,
    Scorer,
    StateAdapter,
    StateResetError,
    TargetRunner,
    _uses_judge,
)
from .core.types import (
    EvalItem,
    ItemResult,
    RunContext,
    RunResult,
    ScoreAggregate,
    ScoreResult,
)
from .langfuse_client import LangfuseClient, observe
from .plugins import DATASETS, JUDGES, SCORERS, SINKS, STATE_ADAPTERS, TARGETS, bootstrap

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


def _make_item_rng(base_seed: int, item_index: int) -> random.Random:
    """Create a deterministic per-item RNG.

    Each item receives ``Random(base_seed + item_index)`` so the random stream
    is identical regardless of thread scheduling.
    """
    return random.Random(base_seed + item_index)


class EvalEngine:
    """Orchestrates a single evaluation run.

    Loads dataset items, runs them through the target and scorers, aggregates
    results, and emits them to configured sinks.  Supports both sequential
    (``max_workers=1``) and parallel (``max_workers>1``) item execution.
    """

    def __init__(
        self,
        config: EvalConfig,
        *,
        dataset: DatasetSource,
        target: TargetRunner,
        scorers: list[Scorer],
        sinks: list[ResultSink],
        judge: Judge | None = None,
        state_adapter: StateAdapter | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.config = config
        self.dataset = dataset
        self.target = target
        # F-057: judges sort after programmatic scorers; a judge never runs once one has failed.
        self.scorers = sorted(scorers, key=_uses_judge)
        self.sinks = sinks
        self.judge = judge
        self.state_adapter = state_adapter
        # Serializes target.run() itself when a state adapter is configured -- see
        # core/_state_lifecycle.py's module docstring for the concurrency rationale.
        self._state_lock = threading.Lock()
        self.rng = rng or random.Random(config.run.seed)
        self.clock = clock
        self.langfuse_client: LangfuseClient | None = None

    @classmethod
    def from_config(
        cls,
        config: EvalConfig,
        *,
        langfuse_client: LangfuseClient | None = None,
    ) -> EvalEngine:
        """Build an engine from a validated ``EvalConfig``.

        Bootstraps the plugin registry, instantiates every component by its
        registered ``type`` name, and optionally wires a Langfuse client into
        client-aware components.
        """
        bootstrap()
        dataset = DATASETS.create(config.dataset.type, config.dataset.params)
        target = TARGETS.create(config.target.type, config.target.params)
        scorers = [SCORERS.create(s.type, s.params) for s in config.scorers]
        judge = None
        if config.judge is not None:
            judge_params = config.judge.params
            # F-026: resolve the judge system prompt from Langfuse (or YAML fallback)
            # and inject it as the judge's `system` param. Additive — absent
            # judge_prompt leaves params untouched.
            judge_prompt = getattr(config, "judge_prompt", None)
            if judge_prompt is not None:
                from .prompts import resolve_prompt

                resolved = resolve_prompt(judge_prompt, cast(Any, langfuse_client))
                if resolved is not None:
                    judge_params = {**judge_params, "system": resolved}
            judge = JUDGES.create(config.judge.type, judge_params)
        sinks = [SINKS.create(s.type, s.params) for s in config.sinks]
        state_adapter = None
        if config.state_adapter is not None:
            state_adapter = STATE_ADAPTERS.create(config.state_adapter.type, config.state_adapter.params)

        # Wrap the judge with a cost cap when enabled (F-022). Imported lazily so
        # the offline path never pulls in agent_core unless budgeting is on.
        #
        # This must precede client injection below. When it ran *after*, the loop
        # attached to the raw judge and the wrapper then replaced it, so
        # BudgetedJudge.attach_client — which exists to delegate inward — was never
        # reached on this path: unit-tested, production-unreachable. Tracing still
        # worked only because OpenAIJudge.attach_client mutates its own client, an
        # accident that would not survive a wrapper holding client state of its own.
        judge_budget = getattr(config, "judge_budget", None)
        if judge is not None and judge_budget is not None and judge_budget.enabled:
            adapter = import_module("eval_harness.agent_core_adapter")
            build_budgeted_judge = getattr(adapter, "build_budgeted_judge", None)
            if build_budgeted_judge is None:  # pragma: no cover - defensive compatibility guard
                raise RuntimeError("eval_harness.agent_core_adapter.build_budgeted_judge is unavailable")
            judge = build_budgeted_judge(judge, judge_budget)

        # Inject the Langfuse client into any client-aware component. `judge` is now
        # whatever the engine will actually call, wrapper included.
        if langfuse_client is not None:
            for component in [dataset, judge, *sinks]:
                if component is not None and hasattr(component, "attach_client"):
                    component.attach_client(langfuse_client)

        engine = cls(
            config,
            dataset=dataset,
            target=target,
            scorers=scorers,
            sinks=sinks,
            judge=judge,
            state_adapter=state_adapter,
        )
        engine.langfuse_client = langfuse_client
        return engine

    def _sample(self, items: list[EvalItem]) -> list[EvalItem]:
        """Apply probabilistic sampling using the run-level RNG."""
        rate = self.config.run.sample_rate
        if rate >= 1.0:
            return items
        return [it for it in items if self.rng.random() < rate]

    @observe()
    def _run_one(
        self,
        item: EvalItem,
        ctx: RunContext,
        *,
        attempt_index: int | None = None,
        item_run_id: str | None = None,
    ) -> ItemResult:
        """Execute the target and all scorers for a single dataset item.

        ``attempt_index``/``item_run_id`` are set only for one of several repeated
        attempts (``repetitions > 1``); left ``None`` for the legacy single-attempt
        call, so the returned ``ItemResult`` serializes byte-identically to the
        pre-reliability-metrics harness (mirrors the ``trajectory`` precedent,
        ADR 0031 obligation 4).

        When ``self.state_adapter`` is configured, ``run_state_bracketed_attempt``
        (``core/_state_lifecycle.py``) brackets ``target.run`` with the adapter's
        reset/snapshot/evaluate lifecycle; unconfigured is a strict no-op (ADR
        0031 obligation 1).
        """
        from .langfuse_client import langfuse_context

        state_score: ScoreResult | None = None
        if self.state_adapter is not None:
            output, state_score = run_state_bracketed_attempt(
                target=self.target, state_adapter=self.state_adapter, lock=self._state_lock, item=item, ctx=ctx
            )
        else:
            output = self.target.run(item)

        scores: list[ScoreResult] = []
        programmatic_failed = False
        if state_score is not None:
            scores.append(state_score)
            programmatic_failed = True
        for scorer in self.scorers:
            # F-057: skip a judge once a programmatic scorer has failed (routing, not an outcome).
            if _uses_judge(scorer) and programmatic_failed:
                logger.debug(
                    "item=%r: skipping judge scorer %r, a programmatic scorer already failed",
                    item.id,
                    getattr(scorer, "name", "scorer"),
                )
                continue
            try:
                scores.append(result := scorer.score(item, output, ctx))
                if not _uses_judge(scorer) and result.passed is False:
                    programmatic_failed = True
            except Exception as exc:
                scores.append(
                    ScoreResult(
                        name=getattr(scorer, "name", "scorer"),
                        value=0.0,
                        passed=False,
                        comment=f"scorer error: {exc}",
                    )
                )
                if self.config.run.fail_fast:
                    raise
                if not _uses_judge(scorer):
                    programmatic_failed = True

        # Link trace to dataset item if client is available
        client = getattr(self, "langfuse_client", None)
        if client is not None:
            trace_id = langfuse_context.get_current_trace_id()
            if trace_id:
                run_name = self.config.run.run_id or f"{self.config.run.name}"
                client.link_dataset_item(
                    item_id=item.id,
                    trace_id=trace_id,
                    run_name=run_name,
                )

        attempt_id = f"{item.id}:{attempt_index}" if attempt_index is not None else None
        return ItemResult(
            item=item,
            output=output,
            scores=scores,
            attempt_index=attempt_index,
            attempt_id=attempt_id,
            item_run_id=item_run_id,
        )

    def _run_one_safe(
        self,
        index: int,
        item: EvalItem,
        ctx: RunContext,
        *,
        attempt_index: int | None = None,
        item_run_id: str | None = None,
    ) -> tuple[int, ItemResult | Exception]:
        """Thread-safe wrapper around ``_run_one``.

        Returns ``(index, result)`` on success or ``(index, exception)`` on
        failure, so the caller can reconstruct submission-order results and
        handle errors without losing track of which item failed. ``index`` is the
        item's position, shared by every attempt of that item — list.sort's
        stability then preserves attempt submission order within each item without
        needing a compound sort key.
        """
        log_extra: dict[str, Any] = {"item_id": item.id, "item_index": index}
        if attempt_index is not None:
            log_extra["attempt_index"] = attempt_index
        item_logger = logging.LoggerAdapter(logger, log_extra)
        try:
            item_logger.debug("Starting item %s (index=%d)", item.id, index)
            # At repetitions=1 this calls _run_one(item, ctx) — the exact original
            # two-argument call — rather than always passing the new kwargs, so a
            # caller holding a reference to the old two-parameter signature (e.g. a
            # test double replacing _run_one) keeps working unchanged.
            if attempt_index is None and item_run_id is None:
                result = self._run_one(item, ctx)
            else:
                result = self._run_one(item, ctx, attempt_index=attempt_index, item_run_id=item_run_id)
            item_logger.debug("Completed item %s (index=%d)", item.id, index)
            return (index, result)
        except StateResetError:
            raise  # never swallowed -- always aborts the run, regardless of fail_fast
        except Exception as exc:
            item_logger.error("Item %s (index=%d) failed: %s", item.id, index, exc)
            return (index, exc)

    @staticmethod
    def _aggregate(results: list[ItemResult]) -> dict[str, ScoreAggregate]:
        """Aggregate per-item scores into per-scorer summary statistics."""
        buckets: dict[str, list[ScoreResult]] = {}
        for ir in results:
            for s in ir.scores:
                buckets.setdefault(s.name, []).append(s)
        aggregate: dict[str, ScoreAggregate] = {}
        for name, scores in buckets.items():
            values = [s.value for s in scores]
            passes = [s.passed for s in scores if s.passed is not None]
            pass_rate = (sum(1 for p in passes if p) / len(passes)) if passes else None
            aggregate[name] = ScoreAggregate(
                count=len(scores),
                mean=statistics.fmean(values) if values else 0.0,
                pass_rate=pass_rate,
            )
        return aggregate

    def _run_parallel(self, items: list[EvalItem], started: datetime, run_id: str) -> list[ItemResult]:
        """Execute items — and, when ``repetitions > 1``, each item's attempts —
        in parallel via ``ThreadPoolExecutor``.

        Every ``(item, attempt)`` pair gets its own submission and its own
        ``RunContext``, RNG freshly seeded from ``base_seed + item_index`` —
        never advanced across attempts of the same item, only ever re-derived
        from this loop's own ``enumerate()`` index (not ``ctx.item_index``, which
        nothing reads back). At ``repetitions == 1`` this submits exactly one
        future per item with ``attempt_index=None``, identical to the pre-
        reliability-metrics engine. Results are collected in submission order —
        item-major, attempts ascending within an item. On ``fail_fast``, the
        executor is shut down immediately.
        """
        max_workers = self.config.run.max_workers
        base_seed = self.config.run.seed
        repetitions = self.config.run.repetitions
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
                    ctx = RunContext(
                        config=self.config,
                        judge=self.judge,
                        rng=item_rng,
                        now=started,
                        item_index=idx,
                    )
                    futures.append(
                        executor.submit(
                            self._run_one_safe,
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
                    if self.config.run.fail_fast:
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                else:
                    collected.append((index, result_or_exc))

        if first_error is not None and self.config.run.fail_fast:
            raise first_error

        # Sort by submission index to guarantee deterministic ordering
        collected.sort(key=lambda pair: pair[0])
        return [result for _, result in collected]

    @observe()
    def run(self) -> RunResult:
        """Execute the full evaluation pipeline.

        When ``max_workers == 1``, items are processed sequentially (identical
        to the original engine behaviour).  When ``max_workers > 1``, items are
        dispatched to a thread pool for parallel execution. When
        ``run.repetitions > 1``, each item is attempted that many independent
        times through the full scorer lifecycle (see ``_run_sequential_repeated``
        / ``_run_parallel``) — attempt expansion happens here, after the
        duplicate-item-ID check below, so a legitimately repeated item never
        trips it.
        """
        started = self.clock()
        items = self._sample(list(self.dataset.load()))

        # Check for duplicate item IDs
        seen_ids = set()
        for item in items:
            if item.id in seen_ids:
                logger.warning(
                    "Duplicate item ID detected in dataset: %s. "
                    "This may cause tracing, aggregation, or reporting issues.",
                    item.id,
                )
            else:
                seen_ids.add(item.id)

        run_id = self.config.run.run_id or f"{self.config.run.name}-{uuid.uuid4().hex[:8]}"
        max_workers = self.config.run.max_workers
        repetitions = self.config.run.repetitions

        if max_workers == 1:
            if repetitions == 1:
                # --- Sequential path: EXACTLY the original behaviour ---
                ctx = RunContext(config=self.config, judge=self.judge, rng=self.rng, now=started)
                results = [self._run_one(item, ctx) for item in items]
            else:
                results = self._run_sequential_repeated(items, started, run_id)
        else:
            # --- Parallel path ---
            results = self._run_parallel(items, started, run_id)

        aggregate = self._aggregate(results)
        diagnostics = self._run_reliability_diagnostics(results)

        run = RunResult(
            run_id=run_id,
            config_name=self.config.run.name,
            items=results,
            aggregate=aggregate,
            started_at=started,
            finished_at=self.clock(),
            diagnostics=diagnostics,
        )
        for sink in self.sinks:
            sink.emit(run)
        return run

    def _run_sequential_repeated(self, items: list[EvalItem], started: datetime, run_id: str) -> list[ItemResult]:
        """Execute items sequentially with ``repetitions > 1``.

        The single-attempt sequential path (``run()``, above) threads one shared,
        continuously-advancing ``self.rng`` across every item — the original
        engine behaviour, preserved unchanged for ``repetitions == 1``. Here, each
        attempt instead gets its own RNG freshly constructed from ``base_seed +
        item_index`` — the same per-item seed every attempt, never advanced
        between attempts of that item — so a scorer that draws from ``ctx.rng``
        cannot manufacture cross-attempt flakiness from RNG drift alone (see
        design.md "Seeding — and why it is not the lever"). Seeds are derived
        from this loop's own ``enumerate()`` index, never ``ctx.item_index``
        (which the single-attempt sequential path never sets, and nothing reads).
        """
        base_seed = self.config.run.seed
        repetitions = self.config.run.repetitions
        results: list[ItemResult] = []
        for idx, item in enumerate(items):
            item_run_id = f"{run_id}:{item.id}"
            for attempt in range(repetitions):
                ctx = RunContext(
                    config=self.config,
                    judge=self.judge,
                    rng=_make_item_rng(base_seed, idx),
                    now=started,
                    item_index=idx,
                )
                results.append(self._run_one(item, ctx, attempt_index=attempt, item_run_id=item_run_id))
        return results

    def _run_reliability_diagnostics(self, results: list[ItemResult]) -> list[dict[str, str]]:
        """Detect the ADR 0029 vacuous-pass case. See ``core/_reliability_diagnostics.py``
        for the detection logic itself (split out to stay under the size budget)."""
        repetitions = self.config.run.repetitions
        if repetitions <= 1:
            # Guard stays here, not just in the extracted function: skips the
            # target.is_deterministic() call entirely at repetitions==1, matching
            # the pre-extraction behavior exactly (a target stub need not implement
            # is_deterministic() unless repetitions>1 is actually used).
            return []
        return _reliability_diagnostics(
            results,
            repetitions=repetitions,
            declared_deterministic=self.target.is_deterministic(),
        )
