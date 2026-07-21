"""Phoenix score-export sink — offline tests.

``NullPhoenixScoreClient`` + ``PhoenixSink`` are exercised end-to-end with no
network. The SDK client (which emits eval scores as OpenTelemetry spans) is tested
against an injected fake tracer — never the real ``phoenix`` package, which is not
installed in the air-gapped suite.
"""

from __future__ import annotations

import logging
import sys
import types
from types import SimpleNamespace
from typing import cast

from eval_harness.core.types import RunResult
from eval_harness.phoenix_client import (
    NullPhoenixScoreClient,
    SDKPhoenixScoreClient,
    build_score_client,
)
from eval_harness.plugins import SINKS
from eval_harness.sinks import PhoenixSink


def _run(*scores: tuple[str, float, str | None]) -> RunResult:
    """A RunResult-shaped stand-in (the sink only reads these attributes)."""
    stand_in = SimpleNamespace(
        run_id="run-1",
        items=[
            SimpleNamespace(
                item=SimpleNamespace(id="item-1"),
                scores=[SimpleNamespace(name=n, value=v, comment=c) for (n, v, c) in scores],
            )
        ],
    )
    # The sink only reads attributes, so the duck-typed namespace suffices at runtime; the
    # cast keeps the static type honest without building a full RunResult.
    return cast(RunResult, stand_in)


def _phoenix_sink(params: dict[str, object]) -> PhoenixSink:
    """Create the registered PhoenixSink, narrowed from the ResultSink protocol."""
    sink = SINKS.create("phoenix", params)
    assert isinstance(sink, PhoenixSink)
    return sink


def _null_client(sink: PhoenixSink) -> NullPhoenixScoreClient:
    """Narrow the sink's offline score client so its recording attrs (scores/flushed) type."""
    client = sink._client
    assert isinstance(client, NullPhoenixScoreClient)
    return client


class _RecordingSpan:
    def __init__(self) -> None:
        self.attrs: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_attribute(self, key, value) -> None:
        self.attrs[key] = value


class _RecordingTracer:
    def __init__(self) -> None:
        self.span_names: list[str] = []
        self.last_span: _RecordingSpan | None = None

    def start_as_current_span(self, name):
        self.span_names.append(name)
        self.last_span = _RecordingSpan()
        return self.last_span


def _install_fake_otel_stack(monkeypatch, tracer) -> None:
    """Make ``_otel_tracer()`` resolve to ``tracer`` offline (gate on phoenix + otel)."""
    phoenix = types.ModuleType("phoenix")
    p_otel = types.ModuleType("phoenix.otel")
    p_otel.register = lambda **k: None  # type: ignore[attr-defined]
    phoenix.otel = p_otel  # type: ignore[attr-defined]
    otel = types.ModuleType("opentelemetry")
    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.get_tracer = lambda _n: tracer  # type: ignore[attr-defined]
    otel.trace = trace_mod  # type: ignore[attr-defined]
    for name, mod in [
        ("phoenix", phoenix),
        ("phoenix.otel", p_otel),
        ("opentelemetry", otel),
        ("opentelemetry.trace", trace_mod),
    ]:
        monkeypatch.setitem(sys.modules, name, mod)


# -- Null client -------------------------------------------------------------


def test_null_score_client_records_and_flushes() -> None:
    c = NullPhoenixScoreClient()
    c.log_score(run_id="r", item_id="i", name="acc", value=0.9, comment="ok")
    c.flush()
    assert c.scores == [{"run_id": "r", "item_id": "i", "name": "acc", "value": 0.9, "comment": "ok"}]
    assert c.flushed is True


# -- build_score_client factory ---------------------------------------------


def test_build_score_client_returns_null_when_disabled() -> None:
    assert isinstance(build_score_client(enabled=False), NullPhoenixScoreClient)


def test_build_score_client_falls_back_to_null_without_sdk(monkeypatch, caplog) -> None:
    # Simulate the SDK being absent (hermetic even with the phoenix extra installed):
    # a None entry forces the lazy `from phoenix.otel import register` to ImportError.
    monkeypatch.setitem(sys.modules, "phoenix.otel", None)
    with caplog.at_level(logging.WARNING):
        client = build_score_client(enabled=True)  # phoenix absent → warn + no-op
    assert isinstance(client, NullPhoenixScoreClient)
    assert any("phoenix" in r.message.lower() for r in caplog.records)


def test_build_score_client_returns_sdk_when_backend_present(monkeypatch) -> None:
    _install_fake_otel_stack(monkeypatch, _RecordingTracer())
    assert isinstance(build_score_client(enabled=True), SDKPhoenixScoreClient)


# -- SDK client emits spans --------------------------------------------------


def test_sdk_score_client_emits_span_attributes() -> None:
    tracer = _RecordingTracer()
    client = SDKPhoenixScoreClient(tracer)
    client.log_score(run_id="r", item_id="i", name="acc", value=0.9, comment="ok")
    client.flush()
    assert tracer.span_names == ["eval.score.acc"]
    assert tracer.last_span is not None
    assert tracer.last_span.attrs["eval.run_id"] == "r"
    assert tracer.last_span.attrs["eval.item_id"] == "i"
    assert tracer.last_span.attrs["eval.score.value"] == 0.9
    assert tracer.last_span.attrs["eval.score.comment"] == "ok"


def test_sdk_score_client_log_score_is_failsafe(caplog) -> None:
    class _BoomTracer:
        def start_as_current_span(self, name):
            raise RuntimeError("otel down")

    client = SDKPhoenixScoreClient(_BoomTracer())
    with caplog.at_level(logging.ERROR):
        client.log_score(run_id="r", item_id="i", name="acc", value=0.9)  # must not raise
    assert caplog.records


def test_sdk_score_client_omits_comment_attribute_when_absent() -> None:
    tracer = _RecordingTracer()
    client = SDKPhoenixScoreClient(tracer)
    client.log_score(run_id="r", item_id="i", name="acc", value=0.5)  # no comment
    assert tracer.last_span is not None
    assert "eval.score.comment" not in tracer.last_span.attrs


# -- PhoenixSink (via the dynamic registry — zero engine wiring) -------------


def test_phoenix_sink_registered_and_logs_scores_offline() -> None:
    sink = _phoenix_sink({})  # enabled defaults False → Null client, no network
    sink.emit(_run(("acc", 0.9, "ok"), ("f1", 0.5, None)))
    assert [s["name"] for s in _null_client(sink).scores] == ["acc", "f1"]
    assert _null_client(sink).flushed is True


def test_phoenix_sink_respects_min_value_to_log() -> None:
    sink = _phoenix_sink({"min_value_to_log": 0.6})
    sink.emit(_run(("acc", 0.9, None), ("low", 0.3, None)))
    assert [s["name"] for s in _null_client(sink).scores] == ["acc"]  # 0.3 filtered out
