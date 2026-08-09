"""Tests for `scripts/smokes/phoenix_smoke.py`.

The point of this smoke is that it must FAIL when no collector is listening. An earlier
version passed against a dead endpoint — OTLP export is fire-and-forget, so `register()`
succeeds, `force_flush()` reports nothing, and the span is dropped. The reachability probe
is therefore load-bearing, and `test_unreachable_endpoint_fails` is the test that matters
most in this file.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts" / "smokes"))

import _smoke_lib as lib
import phoenix_smoke as ps


@pytest.fixture
def endpoint_env(monkeypatch: pytest.MonkeyPatch):
    """Set PHOENIX_COLLECTOR_ENDPOINT to an arbitrary value."""

    def _set(value: str = "http://127.0.0.1:6006/v1/traces") -> None:
        monkeypatch.setenv(ps.ENV_ENDPOINT, value)

    return _set


def _free_port() -> int:
    """A port with nothing on it: bind to :0, read the assignment, release it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


class TestResolveTarget:
    """Pure parsing — no I/O, no monkeypatching."""

    @pytest.mark.parametrize(
        ("endpoint", "expected"),
        [
            ("http://example.test", ("example.test", 80)),
            ("https://example.test", ("example.test", 443)),
            ("http://example.test:9999", ("example.test", 9999)),
            ("https://example.test:6006/v1/traces", ("example.test", 6006)),
        ],
    )
    def test_applies_scheme_default_and_respects_explicit_port(self, endpoint, expected) -> None:
        assert ps.resolve_target(endpoint) == expected

    @pytest.mark.parametrize("endpoint", ["nonsense", "", "http:///only-a-path"])
    def test_returns_none_when_no_host(self, endpoint: str) -> None:
        assert ps.resolve_target(endpoint) is None

    def test_unknown_scheme_falls_back_to_port_80(self) -> None:
        assert ps.resolve_target("ftp://example.test") == ("example.test", 80)


class TestCollectorReachable:
    def test_true_against_a_real_listener(self) -> None:
        """A real socket, not a fake — this is the one behaviour that must not be
        simulated, since simulating it is exactly how the bug got in."""
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = int(server.getsockname()[1])
            ok, detail = ps.collector_reachable(f"http://127.0.0.1:{port}")
            assert ok is True
            assert detail == f"127.0.0.1:{port}"
        finally:
            server.close()

    def test_false_when_connection_refused(self) -> None:
        ok, detail = ps.collector_reachable(f"http://127.0.0.1:{_free_port()}")
        assert ok is False
        assert "unreachable" in detail

    def test_false_on_dns_failure_without_real_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a, **_k):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(ps.socket, "create_connection", _boom)
        ok, detail = ps.collector_reachable("http://nonexistent.invalid")
        assert ok is False
        assert "gaierror" in detail

    def test_false_and_no_socket_attempted_when_unparseable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attempted: list[object] = []
        monkeypatch.setattr(ps.socket, "create_connection", lambda *a, **k: attempted.append(a))
        ok, detail = ps.collector_reachable("nonsense")
        assert ok is False
        assert "cannot parse a host" in detail
        assert attempted == [], "must not attempt a connection when there is no host"

    def test_passes_resolved_host_and_port_to_the_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple] = []

        def _record(address, timeout=None):
            seen.append(address)
            raise OSError("stop here")

        monkeypatch.setattr(ps.socket, "create_connection", _record)
        ps.collector_reachable("https://example.test")
        assert seen == [("example.test", 443)]

    def test_uses_the_configured_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def _record(address, timeout=None):
            seen["timeout"] = timeout
            raise OSError("stop here")

        monkeypatch.setattr(ps.socket, "create_connection", _record)
        ps.collector_reachable("http://example.test")
        assert seen["timeout"] == ps.CONNECT_TIMEOUT_SECONDS


class _FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        """None, not False: mypy rejects a `bool` __exit__ that can only return False."""
        return None


class _FakeTracer:
    def __init__(self, raise_on_span: BaseException | None = None) -> None:
        self.raise_on_span = raise_on_span
        self.spans: list[str] = []

    def start_as_current_span(self, name: str):
        if self.raise_on_span:
            raise self.raise_on_span
        self.spans.append(name)
        return _FakeSpan()


class _FakeProvider:
    def __init__(self, tracer: _FakeTracer, *, with_flush: bool = True, flush_raises=None) -> None:
        self._tracer = tracer
        self.flushed = 0
        self._flush_raises = flush_raises
        if with_flush:
            self.force_flush = self._force_flush  # type: ignore[assignment]

    def get_tracer(self, _name: str) -> _FakeTracer:
        return self._tracer

    def _force_flush(self) -> None:
        if self._flush_raises:
            raise self._flush_raises
        self.flushed += 1


@pytest.fixture
def reachable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ps, "collector_reachable", lambda _e: (True, "127.0.0.1:6006"))


@pytest.fixture
def fake_tracing(monkeypatch: pytest.MonkeyPatch):
    """Patch `configure_tracing` on its *source* module.

    `main()` imports it locally inside the function body, so there is no module attribute
    on `phoenix_smoke` to patch; the import re-resolves per call, which makes patching the
    source effective and leak-free.
    """
    import eval_harness.phoenix_client as pc

    def _install(result, capture: list | None = None):
        def _fake(config):
            if capture is not None:
                capture.append(config)
            return result

        monkeypatch.setattr(pc, "configure_tracing", _fake)

    return _install


class TestMain:
    def test_skips_when_endpoint_unset(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.delenv(ps.ENV_ENDPOINT, raising=False)
        assert ps.main() == lib.SKIP_EXIT_CODE
        assert "SKIP" in capsys.readouterr().out

    def test_unreachable_endpoint_fails(self, endpoint_env, monkeypatch, capsys) -> None:
        """The regression guard. Before the probe existed this returned 0."""
        endpoint_env(f"http://127.0.0.1:{_free_port()}")
        assert ps.main() == lib.FAIL_EXIT_CODE
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "Start the collector" in out

    def test_fails_when_phoenix_client_absent(self, endpoint_env, reachable, monkeypatch, capsys) -> None:
        """`sys.modules[...] = None` forces ImportError on a first-party module the same way
        it does for an optional SDK -- the import machinery consults sys.modules first
        regardless of why the entry is None."""
        monkeypatch.setitem(sys.modules, "eval_harness.phoenix_client", None)
        endpoint_env()
        assert ps.main() == lib.FAIL_EXIT_CODE
        assert "cannot import client" in capsys.readouterr().out

    def test_fails_when_configure_tracing_returns_none(self, endpoint_env, reachable, fake_tracing, capsys) -> None:
        endpoint_env()
        fake_tracing(None)
        assert ps.main() == lib.FAIL_EXIT_CODE
        assert "configure_tracing returned None" in capsys.readouterr().out

    def test_disables_auto_instrument_so_the_result_is_extras_independent(
        self, endpoint_env, reachable, fake_tracing
    ) -> None:
        endpoint_env()
        captured: list = []
        fake_tracing(_FakeProvider(_FakeTracer()), capture=captured)
        ps.main()
        assert len(captured) == 1
        config = captured[0]
        assert config.enabled is True
        assert config.tracing is True
        assert config.auto_instrument is False
        assert config.project_name == ps.PROJECT_NAME

    def test_success_emits_a_span_and_flushes(self, endpoint_env, reachable, fake_tracing, capsys) -> None:
        endpoint_env()
        tracer = _FakeTracer()
        provider = _FakeProvider(tracer)
        fake_tracing(provider)

        assert ps.main() == lib.OK_EXIT_CODE
        assert tracer.spans == [ps.SPAN_NAME], "the span must actually be emitted, not just claimed"
        assert provider.flushed == 1, "force_flush must actually be called"
        assert "OK" in capsys.readouterr().out

    def test_success_when_provider_has_no_force_flush(self, endpoint_env, reachable, fake_tracing) -> None:
        endpoint_env()
        fake_tracing(_FakeProvider(_FakeTracer(), with_flush=False))
        assert ps.main() == lib.OK_EXIT_CODE

    def test_fails_when_span_creation_raises(self, endpoint_env, reachable, fake_tracing, capsys) -> None:
        endpoint_env()
        fake_tracing(_FakeProvider(_FakeTracer(raise_on_span=RuntimeError("no tracer"))))
        assert ps.main() == lib.FAIL_EXIT_CODE
        assert "RuntimeError" in capsys.readouterr().out

    def test_fails_when_flush_raises(self, endpoint_env, reachable, fake_tracing, capsys) -> None:
        endpoint_env()
        fake_tracing(_FakeProvider(_FakeTracer(), flush_raises=RuntimeError("drain failed")))
        assert ps.main() == lib.FAIL_EXIT_CODE
        assert "drain failed" in capsys.readouterr().out
