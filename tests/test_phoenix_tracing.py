"""Phoenix tracing seam — offline tests.

Real Phoenix is NOT installed in the air-gapped suite, so the SDK paths are
exercised via ``sys.modules`` injection of a fake ``phoenix.otel`` module — NOT
``unittest.mock.patch("phoenix.otel.register")``, which would raise
``ModuleNotFoundError`` at patch-resolution time when ``phoenix`` is absent.
The no-op / ImportError fallbacks run for real here (phoenix genuinely missing).
"""

from __future__ import annotations

import logging
import sys
import types

from eval_harness.config.models import PhoenixConfig
from eval_harness.phoenix_client import configure_tracing, phoenix_observe


def _install_fake_phoenix_otel(monkeypatch, register) -> None:
    """Make ``from phoenix.otel import register`` resolve to ``register`` offline."""
    phoenix = types.ModuleType("phoenix")
    otel = types.ModuleType("phoenix.otel")
    otel.register = register  # type: ignore[attr-defined]
    phoenix.otel = otel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix", phoenix)
    monkeypatch.setitem(sys.modules, "phoenix.otel", otel)


# -- configure_tracing: gating ----------------------------------------------


def test_configure_tracing_returns_none_when_config_absent() -> None:
    assert configure_tracing(None) is None


def test_configure_tracing_returns_none_when_disabled() -> None:
    assert configure_tracing(PhoenixConfig(enabled=False)) is None


def test_configure_tracing_returns_none_when_tracing_off() -> None:
    assert configure_tracing(PhoenixConfig(enabled=True, tracing=False)) is None


# -- configure_tracing: fail-safe (never breaks an eval run) -----------------


def test_configure_tracing_without_sdk_is_failsafe(monkeypatch, caplog) -> None:
    # Simulate the SDK being absent so this is hermetic even when the phoenix extra
    # is installed: a None entry in sys.modules forces the lazy
    # `from phoenix.otel import register` to raise ImportError → warn + None, no exception.
    monkeypatch.setitem(sys.modules, "phoenix.otel", None)
    with caplog.at_level(logging.WARNING):
        result = configure_tracing(PhoenixConfig(enabled=True))
    assert result is None
    assert any("phoenix" in r.message.lower() for r in caplog.records)


def test_configure_tracing_failsafe_when_register_raises(monkeypatch, caplog) -> None:
    def boom(**kwargs):
        raise RuntimeError("collector down")

    _install_fake_phoenix_otel(monkeypatch, boom)
    with caplog.at_level(logging.ERROR):
        result = configure_tracing(PhoenixConfig(enabled=True))
    assert result is None
    assert caplog.records  # the failure was logged for debugging


# -- configure_tracing: success path via injection ---------------------------


def test_configure_tracing_invokes_register_with_env_endpoint(monkeypatch) -> None:
    calls: dict = {}

    def fake_register(**kwargs):
        calls.update(kwargs)
        return "TRACER_PROVIDER"

    _install_fake_phoenix_otel(monkeypatch, fake_register)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")

    result = configure_tracing(PhoenixConfig(enabled=True, project_name="proj", auto_instrument=True, batch=True))
    assert result == "TRACER_PROVIDER"
    assert calls["project_name"] == "proj"
    assert calls["auto_instrument"] is True
    assert calls["batch"] is True
    assert calls["endpoint"] == "http://localhost:6006"  # endpoint sourced from env, not hardcoded


def test_configure_tracing_omits_endpoint_when_env_absent(monkeypatch) -> None:
    calls: dict = {}

    def fake_register(**kwargs):
        calls.update(kwargs)
        return "TP"

    _install_fake_phoenix_otel(monkeypatch, fake_register)
    monkeypatch.delenv("PHOENIX_COLLECTOR_ENDPOINT", raising=False)

    result = configure_tracing(PhoenixConfig(enabled=True))
    assert result == "TP"
    assert "endpoint" not in calls  # let phoenix.otel resolve its own default endpoint


# -- phoenix_observe: transparent no-op decorator (both forms) ---------------


def test_phoenix_observe_is_transparent_noop_without_sdk() -> None:
    @phoenix_observe()
    def add(x: int, y: int) -> int:
        return x + y

    assert add(2, 3) == 5


def test_phoenix_observe_supports_bare_form_without_sdk() -> None:
    @phoenix_observe
    def greet(name: str) -> str:
        return f"hi {name}"

    assert greet("a") == "hi a"


def test_phoenix_observe_opens_span_when_backend_present(monkeypatch) -> None:
    spans: list[str] = []

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Tracer:
        def start_as_current_span(self, name):
            spans.append(name)
            return _Ctx()

    # Gate on phoenix presence, then hand back our fake OTel tracer.
    _install_fake_phoenix_otel(monkeypatch, lambda **k: None)
    otel = types.ModuleType("opentelemetry")
    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.get_tracer = lambda _name: _Tracer()  # type: ignore[attr-defined]
    otel.trace = trace_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", otel)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)

    @phoenix_observe(name="myspan")
    def work() -> int:
        return 42

    assert work() == 42
    assert spans == ["myspan"]  # the callable ran inside a named span
