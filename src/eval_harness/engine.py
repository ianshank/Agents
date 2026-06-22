"""The evaluation engine: orchestrates load -> run -> score -> aggregate -> emit.

The engine holds no behavioural literals. Seed, sampling, component selection
and parameters all come from the validated config; the clock and RNG are
injectable so runs are fully deterministic under test.
"""

from __future__ import annotations

import logging
import random
import statistics
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone

from .config.models import EvalConfig
from .core.interfaces import DatasetSource, Judge, ResultSink, Scorer, TargetRunner
from .core.types import (
    EvalItem,
    ItemResult,
    RunContext,
    RunResult,
    ScoreAggregate,
    ScoreResult,
)
from .langfuse_client import LangfuseClient, observe
from .plugins import DATASETS, JUDGES, SCORERS, SINKS, TARGETS, bootstrap

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(timezone.utc)


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
        rng: random.Random | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.config = config
        self.dataset = dataset
        self.target = target
        self.scorers = scorers
        self.sinks = sinks
        self.judge = judge
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
        judge = JUDGES.create(config.judge.type, config.judge.params) if config.judge else None
        sinks = [SINKS.create(s.type, s.params) for s in config.sinks]

        # Inject the Langfuse client into any client-aware component.
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
    def _run_one(self, item: EvalItem, ctx: RunContext) -> ItemResult:
        """Execute the target and all scorers for a single dataset item."""
        from .langfuse_client import langfuse_context

        output = self.target.run(item)
        scores: list[ScoreResult] = []
        for scorer in self.scorers:
            try:
                scores.append(scorer.score(item, output, ctx))
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

        return ItemResult(item=item, output=output, scores=scores)

    def _run_one_safe(self, index: int, item: EvalItem, ctx: RunContext) -> tuple[int, ItemResult | Exception]:
        """Thread-safe wrapper around ``_run_one``.

        Returns ``(index, result)`` on success or ``(index, exception)`` on
        failure, so the caller can reconstruct submission-order results and
        handle errors without losing track of which item failed.
        """
        item_logger = logging.LoggerAdapter(logger, {"item_id": item.id, "item_index": index})
        try:
            item_logger.debug("Starting item %s (index=%d)", item.id, index)
            result = self._run_one(item, ctx)
            item_logger.debug("Completed item %s (index=%d)", item.id, index)
            return (index, result)
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

    def _run_parallel(self, items: list[EvalItem], started: datetime) -> list[ItemResult]:
        """Execute items in parallel via ``ThreadPoolExecutor``.

        Each item gets a per-item ``RunContext`` with a deterministic RNG seeded
        from ``base_seed + item_index``.  Results are collected in submission
        order.  On ``fail_fast``, the executor is shut down immediately.
        """
        max_workers = self.config.run.max_workers
        base_seed = self.config.run.seed
        logger.info(
            "Parallel execution: %d items with max_workers=%d",
            len(items),
            max_workers,
        )

        collected: list[tuple[int, ItemResult]] = []
        first_error: Exception | None = None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: list[Future[tuple[int, ItemResult | Exception]]] = []
            for idx, item in enumerate(items):
                item_rng = _make_item_rng(base_seed, idx)
                ctx = RunContext(
                    config=self.config,
                    judge=self.judge,
                    rng=item_rng,
                    now=started,
                    item_index=idx,
                )
                futures.append(executor.submit(self._run_one_safe, idx, item, ctx))

            for future in futures:
                index, result_or_exc = future.result()
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
        dispatched to a thread pool for parallel execution.
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

        max_workers = self.config.run.max_workers

        if max_workers == 1:
            # --- Sequential path: EXACTLY the original behaviour ---
            ctx = RunContext(config=self.config, judge=self.judge, rng=self.rng, now=started)
            results = [self._run_one(item, ctx) for item in items]
        else:
            # --- Parallel path ---
            results = self._run_parallel(items, started)

        aggregate = self._aggregate(results)

        run_id = self.config.run.run_id or f"{self.config.run.name}-{uuid.uuid4().hex[:8]}"
        run = RunResult(
            run_id=run_id,
            config_name=self.config.run.name,
            items=results,
            aggregate=aggregate,
            started_at=started,
            finished_at=self.clock(),
        )
        for sink in self.sinks:
            sink.emit(run)
        return run
