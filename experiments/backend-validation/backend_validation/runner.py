"""Probe execution engine: runs probe callables, captures observables, enforces budgets.

A probe is a pure function ``probe(run: ProbeRun) -> None`` that issues operations through
``run.op(...)`` and attaches boolean evidence with ``record.note(...)``. The engine owns
the cross-cutting rules so probes cannot get them wrong: per-probe time budgets are
cooperative (remaining ops become ``timeout`` observables, no thread games), retries apply
ONLY to operations the client declares idempotent (a retried write would distort artifact
counts), backoff is deterministic (no jitter — reproducible evidence), and every retry
count lands in the observable.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from backend_validation.clients import ProbeClient
from backend_validation.logging_util import debug_span, get_logger
from backend_validation.observables import Observable, ObservableLog, OpOutcome
from backend_validation.registry import get_probe
from backend_validation.settings import JudgeSpec, RetrySpec, TimeoutSpec

logger = get_logger(__name__)

_RETRYABLE = ("error", "timeout")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProbeContext:
    """Everything a probe may parameterize on. No hidden globals, fully fake-able."""

    backend_id: str
    run_marker: str  # unique per run; probes namespace created artifacts with it
    rep_index: int = 0
    judge: JudgeSpec | None = None
    control_endpoint: str = ""


@dataclass
class OpRecord:
    """One executed operation plus the probe's attached evidence fields."""

    outcome: OpOutcome
    extra: dict[str, object] = field(default_factory=dict)

    def note(self, **fields: object) -> None:
        self.extra.update(fields)

    def first_artifact(self, default: str = "") -> str:
        return self.outcome.artifact_ids[0] if self.outcome.artifact_ids else default

    @property
    def ok(self) -> bool:
        return self.outcome.status == "ok"


class ProbeRun:
    """The single object handed to probe functions."""

    def __init__(
        self,
        client: ProbeClient,
        ctx: ProbeContext,
        timeouts: TimeoutSpec,
        retries: RetrySpec,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.ctx = ctx
        self.records: list[OpRecord] = []
        self._client = client
        self._retries = retries
        self._clock = clock
        self._sleeper = sleeper
        self._deadline = clock() + timeouts.probe_budget_seconds

    def op(self, operation: str, payload: Mapping[str, object] | None = None) -> OpRecord:
        payload = payload or {}
        if self._clock() > self._deadline:
            outcome = OpOutcome(
                operation=operation,
                status="timeout",
                latency_ms=0.0,
                stderr="probe budget exhausted before this operation ran",
            )
            record = OpRecord(outcome=outcome)
            self.records.append(record)
            return record
        outcome = self._execute_with_retries(operation, payload)
        record = OpRecord(outcome=outcome)
        self.records.append(record)
        return record

    def _execute_with_retries(self, operation: str, payload: Mapping[str, object]) -> OpOutcome:
        retryable = operation in self._client.idempotent_operations
        max_attempts = self._retries.max_attempts if retryable else 1
        attempt = 1
        outcome = self._client.execute(operation, payload)
        while outcome.status in _RETRYABLE and attempt < max_attempts:
            self._sleeper(self._retries.backoff_base_seconds * (2 ** (attempt - 1)))
            attempt += 1
            outcome = self._client.execute(operation, payload)
        if attempt > 1:
            outcome = replace(outcome, retries=attempt - 1)
        return outcome


def run_probe(
    probe_id: str,
    cell_id: str,
    client: ProbeClient,
    ctx: ProbeContext,
    timeouts: TimeoutSpec,
    retries: RetrySpec,
    *,
    log: ObservableLog | None = None,
    now_fn: Callable[[], str] = utc_now_iso,
    clock: Callable[[], float] = time.perf_counter,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[Observable]:
    """Execute one registered probe once and return (and optionally persist) observables."""
    probe = get_probe(probe_id)
    run = ProbeRun(client, ctx, timeouts, retries, clock=clock, sleeper=sleeper)
    with debug_span(logger, "probe", probe_id=probe_id, backend=ctx.backend_id, rep=ctx.rep_index):
        probe(run)
    stamp = now_fn()
    observables = [
        Observable(
            probe_id=probe_id,
            cell_id=cell_id,
            backend=ctx.backend_id,
            rep_index=ctx.rep_index,
            ts_utc=stamp,
            outcome=record.outcome,
            extra=dict(record.extra),
        )
        for record in run.records
    ]
    if log is not None:
        for observable in observables:
            log.append(observable)
    return observables
