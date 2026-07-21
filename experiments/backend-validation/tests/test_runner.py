"""Unit tests for the probe execution engine: budgets, retries, evidence capture."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from backend_validation.clients import NullProbeClient
from backend_validation.observables import ObservableLog, OpOutcome
from backend_validation.registry import register
from backend_validation.runner import ProbeContext, ProbeRun, run_probe
from backend_validation.settings import RetrySpec, TimeoutSpec

TIMEOUTS = TimeoutSpec(op_seconds=5, probe_budget_seconds=100)
RETRIES = RetrySpec(max_attempts=3, backoff_base_seconds=2)
CTX = ProbeContext(backend_id="null", run_marker="m1")


class _FlakyClient(NullProbeClient):
    """Fails N times then succeeds, for retry-policy tests."""

    def __init__(self, fail_times: int, idempotent: bool) -> None:
        super().__init__(backend_id="flaky")
        self.fail_times = fail_times
        if idempotent:
            self.idempotent_operations = frozenset({"fetch_thing"})

    def execute(self, operation: str, payload: Mapping[str, object]) -> OpOutcome:
        self.calls.append((operation, dict(payload)))
        if len(self.calls) <= self.fail_times:
            return OpOutcome(operation=operation, status="error", latency_ms=1.0)
        return OpOutcome(operation=operation, status="ok", latency_ms=1.0)


def test_idempotent_op_retries_with_deterministic_backoff() -> None:
    client = _FlakyClient(fail_times=2, idempotent=True)
    sleeps: list[float] = []
    run = ProbeRun(client, CTX, TIMEOUTS, RETRIES, sleeper=sleeps.append)
    record = run.op("fetch_thing", {})
    assert record.outcome.status == "ok"
    assert record.outcome.retries == 2
    assert sleeps == [2.0, 4.0]  # base * 2^(attempt-1), no jitter
    assert len(client.calls) == 3


def test_non_idempotent_op_is_never_retried() -> None:
    client = _FlakyClient(fail_times=2, idempotent=False)
    sleeps: list[float] = []
    run = ProbeRun(client, CTX, TIMEOUTS, RETRIES, sleeper=sleeps.append)
    record = run.op("write_thing", {})
    assert record.outcome.status == "error" and record.outcome.retries == 0
    assert sleeps == [] and len(client.calls) == 1


def test_retries_exhaust_and_report_final_status() -> None:
    client = _FlakyClient(fail_times=99, idempotent=True)
    run = ProbeRun(client, CTX, TIMEOUTS, RETRIES, sleeper=lambda _s: None)
    record = run.op("fetch_thing", {})
    assert record.outcome.status == "error" and record.outcome.retries == 2
    assert len(client.calls) == RETRIES.max_attempts


def test_budget_exhaustion_marks_remaining_ops_timeout() -> None:
    clock_values = iter([0.0, 0.0, 1000.0])  # construct, first op check, second op check
    client = NullProbeClient()
    run = ProbeRun(
        client,
        CTX,
        TimeoutSpec(op_seconds=5, probe_budget_seconds=10),
        RETRIES,
        clock=lambda: next(clock_values),
        sleeper=lambda _s: None,
    )
    first = run.op("one", {})
    assert first.outcome.status == "ok"
    second = run.op("two", {})
    assert second.outcome.status == "timeout"
    assert "budget exhausted" in second.outcome.stderr
    assert len(client.calls) == 1  # the second op never reached the client


def test_op_record_note_and_first_artifact() -> None:
    run = ProbeRun(NullProbeClient(), CTX, TIMEOUTS, RETRIES, sleeper=lambda _s: None)
    record = run.op("create_trace", {})
    record.note(trace_visible=True)
    assert record.extra == {"trace_visible": True}
    assert record.first_artifact().startswith("null-create_trace")
    empty = ProbeRun(NullProbeClient(default_status="error"), CTX, TIMEOUTS, RETRIES, sleeper=lambda _s: None)
    assert empty.op("x", {}).first_artifact("fallback") == "fallback"


def test_run_probe_wraps_records_into_observables_and_persists(tmp_path: Path) -> None:
    @register("l1.test.runner_roundtrip")  # cleaned up by the conftest registry fixture
    def _test_probe(run: ProbeRun) -> None:
        created = run.op("create_trace", {"name": run.ctx.run_marker})
        created.note(saw_marker=run.ctx.run_marker == "m1")

    log = ObservableLog(tmp_path / "obs.jsonl")
    observables = run_probe(
        "l1.test.runner_roundtrip",
        "test.cell",
        NullProbeClient(),
        CTX,
        TIMEOUTS,
        RETRIES,
        log=log,
        now_fn=lambda: "2026-07-20T00:00:00+00:00",
    )
    assert len(observables) == 1
    observable = observables[0]
    assert observable.probe_id == "l1.test.runner_roundtrip"
    assert observable.cell_id == "test.cell"
    assert observable.backend == "null"
    assert observable.ts_utc == "2026-07-20T00:00:00+00:00"
    assert observable.extra == {"saw_marker": True}
    assert log.read_all() == observables  # crash-safe evidence file matches
