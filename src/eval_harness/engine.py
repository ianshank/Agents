"""The evaluation engine: orchestrates load -> run -> score -> aggregate -> emit.

The engine holds no behavioural literals. Seed, sampling, component selection
and parameters all come from the validated config; the clock and RNG are
injectable so runs are fully deterministic under test.
"""
from __future__ import annotations

import random
import statistics
import uuid
from collections.abc import Callable
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvalEngine:
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
        rate = self.config.run.sample_rate
        if rate >= 1.0:
            return items
        return [it for it in items if self.rng.random() < rate]

    @observe()
    def _run_one(self, item: EvalItem, ctx: RunContext) -> ItemResult:
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

    @staticmethod
    def _aggregate(results: list[ItemResult]) -> dict[str, ScoreAggregate]:
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

    @observe()
    def run(self) -> RunResult:
        started = self.clock()
        items = self._sample(list(self.dataset.load()))
        ctx = RunContext(config=self.config, judge=self.judge, rng=self.rng, now=started)

        results = [self._run_one(item, ctx) for item in items]
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
