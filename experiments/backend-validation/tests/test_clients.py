"""Unit tests for the client layer: Null double, dispatch base, factory, SDK wrappers.

The SDK wrappers are tested against ``sys.modules`` stub SDKs and a fake REST transport —
the pattern that makes the coverage floor real without any network or installed vendor
package.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Mapping
from typing import Any, ClassVar

import pytest

from backend_validation.clients import (
    MissingCredentialsError,
    NullProbeClient,
    build_client,
    unsupported,
)
from backend_validation.clients._dispatch import DispatchProbeClient, OpDraft
from backend_validation.clients._rest import RestResult, basic_auth_header, bearer_auth_header
from backend_validation.observables import OpOutcome
from backend_validation.settings import BackendSpec, JudgeSpec

JUDGE = JudgeSpec(base_url="http://127.0.0.1:18323/v1", model="m", api_key_env="BV_JUDGE_API_KEY")


def _spec(backend_id: str, credential_env: dict[str, str] | None = None) -> BackendSpec:
    return BackendSpec(
        id=backend_id,
        display_name=backend_id,
        base_url="http://127.0.0.1:1",
        compose_file=f"deploy/{backend_id}/compose.yaml",
        sdk_extra=backend_id,
        credential_env=credential_env or {},
    )


class FakeRest:
    """Scripted RestTransport; records every call."""

    def __init__(self, status_code: int = 200, body: str = "{}") -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str]] = []

    def call(self, method: str, url: str, **_kwargs: Any) -> RestResult:
        self.calls.append((method, url))
        return RestResult(status_code=self.status_code, body_excerpt=self.body)


# ------------------------------------------------------------------- null client
def test_null_client_records_and_defaults_ok() -> None:
    client = NullProbeClient(backend_id="x")
    outcome = client.execute("create_trace", {"name": "t"})
    assert outcome.status == "ok" and outcome.artifact_ids
    assert client.calls == [("create_trace", {"name": "t"})]
    client.close()


def test_null_client_scripted_and_default_status() -> None:
    scripted = OpOutcome(operation="fetch_trace", status="error", latency_ms=1.0)
    client = NullProbeClient(script={"fetch_trace": scripted, "probe_endpoint": lambda p: scripted})
    assert client.execute("fetch_trace", {}) is scripted
    assert client.execute("probe_endpoint", {}) is scripted
    failing = NullProbeClient(default_status="error")
    assert failing.execute("anything", {}).status == "error"


def test_unsupported_helper() -> None:
    outcome = unsupported("weird_op")
    assert outcome.status == "unsupported" and outcome.operation == "weird_op"


# ----------------------------------------------------------------- dispatch base
class _ToyClient(DispatchProbeClient):
    backend_id = "toy"

    def _op_good(self, payload: Mapping[str, object]) -> OpDraft:
        return OpDraft(artifact_ids=("a-1",), response_excerpt="fine")

    def _op_boom(self, payload: Mapping[str, object]) -> OpDraft:
        raise RuntimeError("kaput")

    def _ops(self) -> Mapping[str, Any]:
        return {"good": self._op_good, "boom": self._op_boom}


def test_dispatch_measures_latency_and_captures_errors() -> None:
    client = _ToyClient()
    good = client.execute("good", {})
    assert good.status == "ok" and good.artifact_ids == ("a-1",) and good.latency_ms >= 0
    boom = client.execute("boom", {})
    assert boom.status == "error" and "RuntimeError: kaput" in boom.stderr
    missing = client.execute("nope", {})
    assert missing.status == "unsupported"
    client.close()


def test_auth_header_helpers() -> None:
    assert basic_auth_header("u", "p")["Authorization"].startswith("Basic ")
    assert bearer_auth_header("t") == {"Authorization": "Bearer t"}


# ---------------------------------------------------------------------- factory
def test_build_client_disabled_returns_null() -> None:
    client = build_client(_spec("langfuse"), enabled=False)
    assert isinstance(client, NullProbeClient)


def test_build_client_unknown_backend_returns_null() -> None:
    client = build_client(_spec("mysterious"))
    assert isinstance(client, NullProbeClient)


def test_build_client_missing_sdk_returns_null(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langfuse", None)  # import -> ImportError
    spec = _spec("langfuse", {"secret_key": "BV_LF_SK", "public_key": "BV_LF_PK"})
    client = build_client(spec, env={"BV_LF_SK": "s", "BV_LF_PK": "p"})
    assert isinstance(client, NullProbeClient)


def test_build_client_missing_credentials_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "langfuse", types.ModuleType("langfuse"))
    spec = _spec("langfuse", {"secret_key": "BV_LF_SK", "public_key": "BV_LF_PK"})
    with pytest.raises(MissingCredentialsError, match="BV_LF_PK"):
        build_client(spec, env={})


def test_build_client_init_failure_returns_null(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = types.ModuleType("opik")

    class _Boom:
        def __init__(self, **_kwargs: Any) -> None:
            raise RuntimeError("cannot init")

    broken.Opik = _Boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", broken)
    client = build_client(_spec("opik", {"api_key": "BV_OPIK_API_KEY"}), env={})
    assert isinstance(client, NullProbeClient)


# ------------------------------------------------------------- langfuse wrapper
class _FakeTrace:
    id = "trace-1"

    def span(self, **_kwargs: Any) -> _FakeSpan:
        return _FakeSpan()


class _FakeSpan:
    def end(self) -> None:
        return None


class _FakePrompt:
    version = 2
    prompt = "v2-text"


class _FakeDatasetItem:
    id = "item-1"


class _FakeDataset:
    items: ClassVar[list[_FakeDatasetItem]] = [_FakeDatasetItem(), _FakeDatasetItem()]


class _FakeRunItems:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def create(self, request: dict[str, object]) -> None:
        self.requests.append(request)


class _FakeApi:
    def __init__(self) -> None:
        self.dataset_run_items = _FakeRunItems()


class _FakeLangfuseHandle:
    def __init__(self) -> None:
        self.api = _FakeApi()
        self.flushed = 0
        self.scores: list[dict[str, object]] = []

    def trace(self, **_kwargs: Any) -> _FakeTrace:
        return _FakeTrace()

    def fetch_trace(self, trace_id: str) -> Any:
        return types.SimpleNamespace(data=types.SimpleNamespace(name="bv"))

    def create_prompt(self, **_kwargs: Any) -> _FakePrompt:
        return _FakePrompt()

    def get_prompt(self, _name: str) -> _FakePrompt:
        return _FakePrompt()

    def create_dataset(self, **_kwargs: Any) -> None:
        return None

    def create_dataset_item(self, **_kwargs: Any) -> None:
        return None

    def get_dataset(self, _name: str) -> _FakeDataset:
        return _FakeDataset()

    def score(self, **kwargs: Any) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        self.flushed += 1


def _langfuse_client(rest: FakeRest) -> Any:
    from backend_validation.clients.langfuse import LangfuseProbeClient

    return LangfuseProbeClient(
        _FakeLangfuseHandle(), base_url="http://lf", auth={"Authorization": "Basic x"}, rest=rest, judge=JUDGE
    )


def test_langfuse_sdk_ops_produce_expected_evidence() -> None:
    client = _langfuse_client(FakeRest())
    created = client.execute("create_trace", {"name": "t"})
    assert created.status == "ok" and created.artifact_ids == ("trace-1",)
    fetched = client.execute("fetch_trace", {"trace_id": "trace-1"})
    assert "name=bv" in fetched.response_excerpt
    prompt = client.execute("fetch_prompt", {"name": "p"})
    assert "version=2" in prompt.response_excerpt and "v2-text" in prompt.response_excerpt
    dataset = client.execute("fetch_dataset", {"name": "d"})
    assert dataset.response_excerpt == "items=2" and dataset.artifact_ids == ("item-1", "item-1")
    linked = client.execute("link_dataset_run", {"run_name": "r", "item_id": "item-1", "trace_id": "trace-1"})
    assert linked.status == "ok"
    agent = client.execute("create_agent_trace", {"name": "a"})
    assert agent.response_excerpt == "spans=2"
    client.close()


def test_langfuse_rest_ops_route_through_transport() -> None:
    rest = FakeRest(status_code=404, body="not found")
    client = _langfuse_client(rest)
    guard = client.execute("invoke_guardrail", {"text": "x"})
    assert guard.status == "error" and "HTTP 404" in guard.response_excerpt
    judge = client.execute("configure_judge", {})
    assert judge.status == "error"  # 404 evidence, not a crash
    urls = [url for _method, url in rest.calls]
    assert any("/api/public/guardrails/check" in url for url in urls)
    assert any("/api/public/eval-configs" in url for url in urls)


# ----------------------------------------------------------------- opik wrapper
class _FakeOpikPrompt:
    commit = "abc123"
    prompt = "v2-text"


class _FakeOpikDataset:
    def __init__(self) -> None:
        self.inserted: list[list[dict[str, object]]] = []

    def insert(self, items: list[dict[str, object]]) -> None:
        self.inserted.append(items)

    def get_items(self) -> list[dict[str, object]]:
        return [{"id": "item-9"}, {"id": "item-10"}]


class _FakeOpikHandle:
    def __init__(self) -> None:
        self.feedback: list[list[dict[str, object]]] = []
        self._dataset = _FakeOpikDataset()

    def trace(self, **_kwargs: Any) -> _FakeTrace:
        return _FakeTrace()

    def get_trace_content(self, id: str) -> Any:
        return types.SimpleNamespace(name="bv")

    def create_prompt(self, **_kwargs: Any) -> _FakeOpikPrompt:
        return _FakeOpikPrompt()

    def get_prompt(self, **_kwargs: Any) -> _FakeOpikPrompt:
        return _FakeOpikPrompt()

    def get_or_create_dataset(self, **_kwargs: Any) -> _FakeOpikDataset:
        return self._dataset

    def log_traces_feedback_scores(self, scores: list[dict[str, object]]) -> None:
        self.feedback.append(scores)

    def flush(self) -> None:
        return None


def test_opik_ops_produce_expected_evidence() -> None:
    from backend_validation.clients.opik import OpikProbeClient

    rest = FakeRest()
    client = OpikProbeClient(_FakeOpikHandle(), base_url="http://opik", auth={}, rest=rest, judge=JUDGE)
    assert client.execute("create_trace", {}).artifact_ids == ("trace-1",)
    assert "commit=abc123" in client.execute("fetch_prompt", {"name": "p"}).response_excerpt
    dataset = client.execute("fetch_dataset", {"name": "d"})
    assert dataset.artifact_ids == ("item-9", "item-10") and dataset.response_excerpt == "items=2"
    rollback = client.execute("rollback_prompt", {"name": "p", "commit": "abc123"})
    assert rollback.status == "ok"
    scored = client.execute("score_agent_trace", {"trace_id": "trace-1"})
    assert scored.status == "ok"
    compare = client.execute("compare_runs", {"name": "d"})
    assert compare.status == "ok" and any("/experiments" in url for _m, url in rest.calls)
    client.close()


# ------------------------------------------------- every-operation dispatch sweep
_SWEEP_PAYLOAD: dict[str, object] = {
    "name": "n",
    "trace_id": "t-1",
    "item_id": "i-1",
    "run_name": "r-1",
    "url": "http://127.0.0.1:1/",
    "queue_id": "q-1",
    "count": 2,
    "version": 1,
    "commit": "c-1",
    "text": "v2",
    "judge_url": "http://j",
    "otlp_body": {"resourceSpans": []},
}


def test_langfuse_every_declared_op_has_a_working_handler() -> None:
    client = _langfuse_client(FakeRest())
    operations = sorted(client._ops())
    assert len(operations) >= 24  # the full PROBES.yaml operation surface
    for operation in operations:
        outcome = client.execute(operation, _SWEEP_PAYLOAD)
        assert outcome.status in ("ok", "error"), f"{operation} -> {outcome.status}: {outcome.stderr}"
        assert outcome.status != "unsupported"


def test_opik_every_declared_op_has_a_working_handler() -> None:
    from backend_validation.clients.opik import OpikProbeClient

    client = OpikProbeClient(_FakeOpikHandle(), base_url="http://opik", auth={}, rest=FakeRest(), judge=JUDGE)
    operations = sorted(client._ops())
    assert len(operations) >= 24
    for operation in operations:
        outcome = client.execute(operation, _SWEEP_PAYLOAD)
        assert outcome.status in ("ok", "error"), f"{operation} -> {outcome.status}: {outcome.stderr}"


def test_clients_expose_the_same_operation_surface() -> None:
    from backend_validation.clients.opik import OpikProbeClient

    langfuse_ops = set(_langfuse_client(FakeRest())._ops())
    opik_ops = set(OpikProbeClient(_FakeOpikHandle(), base_url="x", auth={}, rest=FakeRest())._ops())
    assert langfuse_ops == opik_ops  # parity: every probe works against both backends


def test_from_spec_constructs_clients_from_stub_sdks(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_validation.clients.langfuse import LangfuseProbeClient
    from backend_validation.clients.opik import OpikProbeClient

    lf_module = types.ModuleType("langfuse")
    lf_module.Langfuse = lambda **_kw: _FakeLangfuseHandle()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", lf_module)
    lf_spec = _spec("langfuse", {"secret_key": "BV_LF_SK", "public_key": "BV_LF_PK"})
    lf_client = build_client(lf_spec, judge=JUDGE, env={"BV_LF_SK": "s", "BV_LF_PK": "p"})
    assert isinstance(lf_client, LangfuseProbeClient)
    lf_client.close()  # flushes the stub handle

    opik_module = types.ModuleType("opik")
    opik_module.Opik = lambda **_kw: _FakeOpikHandle()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    with_key = build_client(_spec("opik", {"api_key": "BV_OPIK_KEY"}), env={"BV_OPIK_KEY": "k"})
    assert isinstance(with_key, OpikProbeClient)
    without_key = build_client(_spec("opik", {"api_key": "BV_OPIK_KEY"}), env={})
    assert isinstance(without_key, OpikProbeClient)  # self-host default: no auth required


def test_build_client_threads_op_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression (Copilot review): settings.timeouts.op_seconds must reach the client, not
    # a hardcoded 30.0. build_client(op_timeout=...) sets the client's REST timeout.
    lf_module = types.ModuleType("langfuse")
    lf_module.Langfuse = lambda **_kw: _FakeLangfuseHandle()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", lf_module)
    spec = _spec("langfuse", {"secret_key": "BV_LF_SK", "public_key": "BV_LF_PK"})
    client = build_client(spec, env={"BV_LF_SK": "s", "BV_LF_PK": "p"}, op_timeout=7.5)
    assert client._timeout == 7.5  # type: ignore[attr-defined]
    # Default (no op_timeout) falls back to the shared constant, not a scattered literal.
    from backend_validation.clients import DEFAULT_OP_TIMEOUT_SECONDS

    default_client = build_client(spec, env={"BV_LF_SK": "s", "BV_LF_PK": "p"})
    assert default_client._timeout == DEFAULT_OP_TIMEOUT_SECONDS  # type: ignore[attr-defined]
