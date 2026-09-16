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
from datetime import UTC, datetime
from functools import partial
from importlib import import_module
from typing import Any, cast

from .config.models import EvalConfig
from .core._execution_strategies import (
    FATAL_RUN_ERRORS,
    ITEM_ERROR_POLICY_RAISE,
    _evaluate_item_scorers,
    _execute_parallel,
    _execute_sequential_repeated,
    run_item_guarded,
)
from .core._execution_strategies import (
    _make_item_rng as _make_item_rng,
)
from .core._reliability_diagnostics import _reliability_diagnostics, item_error_diagnostics
from .core._state_lifecycle import log_state_adapter_configured, run_state_bracketed_attempt
from .core.interfaces import (
    DatasetSource,
    Judge,
    ResultSink,
    Scorer,
    StateAdapter,
    TargetRunner,
    _uses_judge,
)
from .core.types import (
    EvalItem,
    GateDecision,
    ItemResult,
    RunContext,
    RunResult,
    ScoreAggregate,
    ScoreResult,
)
from .gating import GateEvaluator, default_gate_evaluator
from .langfuse_client import LangfuseClient, observe
from .plugins import DATASETS, JUDGES, SCORERS, SINKS, STATE_ADAPTERS, TARGETS, bootstrap

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current time in UTC."""
    return datetime.now(UTC)


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
        gate_evaluator: GateEvaluator = default_gate_evaluator,
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
        self.gate_evaluator = gate_evaluator
        self.langfuse_client: LangfuseClient | None = None

    @classmethod
    def _create_judge(cls, config: EvalConfig, langfuse_client: LangfuseClient | None) -> Judge | None:
        """Instantiate and optionally prompt-resolve and budget-wrap the judge."""
        if config.judge is None:
            return None
        judge_params = config.judge.params
        judge_prompt = getattr(config, "judge_prompt", None)
        if judge_prompt is not None:
            from .prompts import resolve_prompt

            resolved = resolve_prompt(judge_prompt, cast(Any, langfuse_client))
            if resolved is not None:
                judge_params = {**judge_params, "system": resolved}
        judge = JUDGES.create(config.judge.type, judge_params)
        judge_budget = getattr(config, "judge_budget", None)
        if judge_budget is not None and judge_budget.enabled:
            adapter = import_module("eval_harness.agent_core_adapter")
            build_budgeted_judge = getattr(adapter, "build_budgeted_judge", None)
            if build_budgeted_judge is None:  # pragma: no cover - defensive compatibility guard
                raise RuntimeError("eval_harness.agent_core_adapter.build_budgeted_judge is unavailable")
            judge = build_budgeted_judge(judge, judge_budget)
        return judge

    @classmethod
    def _create_state_adapter(cls, config: EvalConfig) -> StateAdapter | None:
        """Instantiate and log the state adapter if configured."""
        if config.state_adapter is None:
            return None
        adapter = STATE_ADAPTERS.create(config.state_adapter.type, config.state_adapter.params)
        log_state_adapter_configured(config.state_adapter.type, config.run.max_workers)
        return adapter

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
        judge = cls._create_judge(config, langfuse_client)
        sinks = [SINKS.create(s.type, s.params) for s in config.sinks]
        state_adapter = cls._create_state_adapter(config)

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

    @property
    def _item_error_policy(self) -> str:
        """The effective policy for an item whose target raises.

        ``fail_fast`` is the stronger statement, so it collapses into
        ``"raise"`` here rather than being re-tested at each execution site.
        Folding it once, in one place, is what keeps the sequential and parallel
        paths from drifting apart again: neither path reads ``fail_fast`` to
        decide *whether* a failure is fatal, only this policy.
        """
        if self.config.run.fail_fast:
            return ITEM_ERROR_POLICY_RAISE
        return str(self.config.run.item_error_policy)

    def _sample(self, items: list[EvalItem]) -> list[EvalItem]:
        """Apply probabilistic sampling using the run-level RNG."""
        rate = self.config.run.sample_rate
        if rate >= 1.0:
            return items
        return [it for it in items if self.rng.random() < rate]

    def _link_langfuse_trace(self, item_id: str) -> None:
        """Link current Langfuse trace to the dataset item if client is attached."""
        client = getattr(self, "langfuse_client", None)
        if client is not None:
            from .langfuse_client import langfuse_context

            trace_id = langfuse_context.get_current_trace_id()
            if trace_id:
                run_name = self.config.run.run_id or f"{self.config.run.name}"
                client.link_dataset_item(
                    item_id=item_id,
                    trace_id=trace_id,
                    run_name=run_name,
                )

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
        state_score: ScoreResult | None = None
        if self.state_adapter is not None:
            output, state_score = run_state_bracketed_attempt(
                target=self.target, state_adapter=self.state_adapter, lock=self._state_lock, item=item, ctx=ctx
            )
        else:
            output = self.target.run(item)

        scores = _evaluate_item_scorers(
            self.scorers,
            item,
            output,
            ctx,
            fail_fast=self.config.run.fail_fast,
            initial_score=state_score,
            item_logger=logger,
        )

        self._link_langfuse_trace(item.id)

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
        except FATAL_RUN_ERRORS:
            raise  # never swallowed -- always aborts the run, regardless of policy
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
        """See ``core/_execution_strategies.py`` for the strategy itself (split
        out to stay under the size budget)."""

        def make_ctx(item_index: int, rng: random.Random) -> RunContext:
            return RunContext(config=self.config, judge=self.judge, rng=rng, now=started, item_index=item_index)

        return _execute_parallel(
            items,
            run_id,
            max_workers=self.config.run.max_workers,
            base_seed=self.config.run.seed,
            repetitions=self.config.run.repetitions,
            make_ctx=make_ctx,
            run_one_safe=self._run_one_safe,
            item_error_policy=self._item_error_policy,
            item_error_score=self.config.run.item_error_score,
        )

    @staticmethod
    def _warn_duplicate_items(items: list[EvalItem]) -> None:
        """Log a warning if duplicate dataset item IDs are detected."""
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

    def _finalize_run(self, run_id: str, results: list[ItemResult], started: datetime) -> RunResult:
        """Aggregate item results, attach diagnostics and gate verdict, and emit to sinks."""
        aggregate = self._aggregate(results)
        diagnostics = [*item_error_diagnostics(results), *self._run_reliability_diagnostics(results)]
        run = RunResult(
            run_id=run_id,
            config_name=self.config.run.name,
            items=results,
            aggregate=aggregate,
            started_at=started,
            finished_at=self.clock(),
            diagnostics=diagnostics,
        )
        run.gate = self._evaluate_gate(run)
        for sink in self.sinks:
            sink.emit(run)
        return run

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
        self._warn_duplicate_items(items)

        run_id = self.config.run.run_id or f"{self.config.run.name}-{uuid.uuid4().hex[:8]}"
        max_workers = self.config.run.max_workers
        repetitions = self.config.run.repetitions

        if max_workers == 1:
            if repetitions == 1:
                results = self._run_sequential_single(items, started)
            else:
                results = self._run_sequential_repeated(items, started, run_id)
        else:
            results = self._run_parallel(items, started, run_id)

        return self._finalize_run(run_id, results, started)

    def _evaluate_gate(self, run: RunResult) -> GateDecision | None:
        """The gate's verdict on *run*, or ``None`` when no gate is configured.

        Delegates to the injected ``gate_evaluator``, which defaults to
        :func:`default_gate_evaluator`. The seam exists so a caller can supply
        a different policy (or a stub, in tests) without the engine growing a
        second code path for it.
        """
        return self.gate_evaluator(self.config.gate, run)

    def _run_sequential_single(self, items: list[EvalItem], started: datetime) -> list[ItemResult]:
        """The single-attempt sequential path: one shared, continuously-advancing
        RNG and one ``RunContext`` across every item -- the original engine
        behaviour, preserved.

        The only change is that a target failure now goes through
        ``run_item_guarded`` like every other path, so ``item_error_policy``
        (never ``max_workers``) decides whether it aborts the run or is recorded
        as a visibly-failed item. A clean run is byte-identical to before.
        ``_run_one(item, ctx)`` keeps its exact two-argument form inside the
        closure, so a test double bound to the legacy signature still resolves.
        """
        ctx = RunContext(config=self.config, judge=self.judge, rng=self.rng, now=started)
        policy = self._item_error_policy
        error_score = self.config.run.item_error_score
        return [
            run_item_guarded(
                partial(self._run_one, item, ctx),
                item,
                item_error_policy=policy,
                item_error_score=error_score,
            )
            for item in items
        ]

    def _run_sequential_repeated(self, items: list[EvalItem], started: datetime, run_id: str) -> list[ItemResult]:
        """See ``core/_execution_strategies.py`` for the strategy itself (split
        out to stay under the size budget)."""

        def make_ctx(item_index: int, rng: random.Random) -> RunContext:
            return RunContext(config=self.config, judge=self.judge, rng=rng, now=started, item_index=item_index)

        return _execute_sequential_repeated(
            items,
            run_id,
            base_seed=self.config.run.seed,
            repetitions=self.config.run.repetitions,
            make_ctx=make_ctx,
            run_one=self._run_one,
            item_error_policy=self._item_error_policy,
            item_error_score=self.config.run.item_error_score,
        )

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
