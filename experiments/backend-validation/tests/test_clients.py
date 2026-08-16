"""Unit tests for the client layer: Null double, dispatch base, factory, SDK wrappers.

The SDK wrappers are tested against ``sys.modules`` stub SDKs and a fake REST transport —
the pattern that makes the coverage floor real without any network or installed vendor
package.
"""

from __future__ import annotations

import sys
import types
import uuid
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

import pytest

from backend_validation.clients import (
    MissingCredentialsError,
    NullProbeClient,
    build_client,
    unsupported,
)
from backend_validation.clients._dispatch import DispatchProbeClient, OpDraft, draft_from_rest
from backend_validation.clients._ids import uuid7
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
    """Scripted RestTransport; records (method, url, headers, json_body) for every call."""

    def __init__(self, status_code: int = 200, body: str = "{}") -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = []

    def call(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
        timeout: float = 30.0,
    ) -> RestResult:
        self.calls.append((method, url, dict(headers or {}), json_body))
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
    urls = [url for _method, url, _headers, _body in rest.calls]
    assert any("/api/public/guardrails/check" in url for url in urls)
    assert any("/api/public/eval-configs" in url for url in urls)


# ----------------------------------------------------------------- opik wrapper
class _FakeOpikPrompt:
    commit = "abc123"
    prompt = "v2-text"


class _FakeOpikDataset:
    id = "ds-1"

    def __init__(self) -> None:
        self.inserted: list[list[dict[str, object]]] = []

    def insert(self, items: list[dict[str, object]]) -> None:
        self.inserted.append(items)

    def get_items(self) -> list[dict[str, object]]:
        return [{"id": "item-9"}, {"id": "item-10"}]


class _FakeOpikExperiment:
    id = "exp-1"

    def __init__(self) -> None:
        self.inserted: list[list[Any]] = []

    def insert(self, experiment_items_references: list[Any]) -> None:
        self.inserted.append(experiment_items_references)


class _FakeFernProjects:
    def __init__(self) -> None:
        self.retrieved: list[str] = []

    def retrieve_project(self, *, name: str) -> Any:
        self.retrieved.append(name)
        return types.SimpleNamespace(id="proj-1", name=name)


class _FakeFernProviderKeys:
    def __init__(self) -> None:
        self.stored: list[dict[str, object]] = []

    def store_llm_provider_api_key(self, **kwargs: Any) -> None:
        self.stored.append(kwargs)


class _FakeFernEvaluators:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def create_automation_rule_evaluator(self, *, request: dict[str, Any]) -> None:
        self.requests.append(request)


class _FakeFernAlerts:
    def __init__(self, existing: int = 1) -> None:
        self.created: list[dict[str, object]] = []
        self._existing = existing

    def create_alert(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    def find_alerts(self) -> Any:
        return types.SimpleNamespace(content=[{"name": "bv-alert"}] * self._existing)


class _FakeFernQueues:
    def __init__(self, existing: int = 1) -> None:
        self.created: list[dict[str, object]] = []
        self.added: list[tuple[str, list[str]]] = []
        self._existing = existing

    def create_annotation_queue(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    def add_items_to_annotation_queue(self, id: str, *, ids: list[str]) -> None:
        self.added.append((id, list(ids)))

    def find_annotation_queues(self) -> Any:
        return types.SimpleNamespace(content=[{"name": "bv-queue"}] * self._existing)


class _FakeFern:
    """The 1.11.x ``rest_client`` (fern OpikApi) namespace, sub-client recorders included."""

    def __init__(self) -> None:
        self.projects = _FakeFernProjects()
        self.llm_provider_key = _FakeFernProviderKeys()
        self.automation_rule_evaluators = _FakeFernEvaluators()
        self.alerts = _FakeFernAlerts()
        self.annotation_queues = _FakeFernQueues()


class _FakeOpikHandle:
    """Surface-present fake mirroring the 1.11.x SDK; older-SDK variants subclass and delete."""

    def __init__(self) -> None:
        self.feedback: list[list[dict[str, object]]] = []
        self._dataset = _FakeOpikDataset()
        self.rest_client = _FakeFern()
        self.experiments: list[_FakeOpikExperiment] = []
        self.prompts: list[dict[str, object]] = []
        self.traces: list[dict[str, object]] = []
        self.searches: list[str] = []
        self.queues: list[str] = []
        self.flushed = 0

    def trace(self, **kwargs: Any) -> _FakeTrace:
        self.traces.append(kwargs)
        return _FakeTrace()

    def get_trace_content(self, id: str) -> Any:
        return types.SimpleNamespace(name="bv", feedback_scores=[{"name": "task_success", "value": 1.0}])

    def search_traces(self, *, filter_string: str) -> list[Any]:
        self.searches.append(filter_string)
        return [types.SimpleNamespace(id="trace-otel-1")]

    def create_prompt(self, **kwargs: Any) -> _FakeOpikPrompt:
        self.prompts.append(kwargs)
        return _FakeOpikPrompt()

    def get_prompt(self, **_kwargs: Any) -> _FakeOpikPrompt | None:
        return _FakeOpikPrompt()

    def get_or_create_dataset(self, **_kwargs: Any) -> _FakeOpikDataset:
        return self._dataset

    def get_dataset(self, _name: str) -> _FakeOpikDataset:
        return self._dataset

    def create_experiment(self, **_kwargs: Any) -> _FakeOpikExperiment:
        experiment = _FakeOpikExperiment()
        self.experiments.append(experiment)
        return experiment

    def create_traces_annotation_queue(self, *, name: str) -> Any:
        self.queues.append(name)
        return types.SimpleNamespace(id="queue-1", name=name)

    def get_traces_annotation_queues(self) -> list[Any]:
        return [types.SimpleNamespace(id="queue-1")]

    def log_traces_feedback_scores(self, scores: list[dict[str, object]]) -> None:
        self.feedback.append(scores)

    def flush(self) -> None:
        self.flushed += 1


class _BareOpikHandle(_FakeOpikHandle):
    """Surface-absent variant (1.7.x has no public ``rest_client``; older SDKs lack the
    rest): drives the fallback arm of every guarded chain."""

    search_traces = None  # type: ignore[assignment]
    create_traces_annotation_queue = None  # type: ignore[assignment]
    get_traces_annotation_queues = None  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        del self.rest_client


def test_opik_ops_produce_expected_evidence() -> None:
    from backend_validation.clients.opik import OpikProbeClient

    rest = FakeRest()
    client = OpikProbeClient(_FakeOpikHandle(), base_url="http://opik", auth={}, rest=rest, judge=JUDGE)
    assert client.execute("create_trace", {}).artifact_ids == ("trace-1",)
    assert "commit=abc123" in client.execute("fetch_prompt", {"name": "p"}).response_excerpt
    dataset = client.execute("fetch_dataset", {"name": "d"})
    assert dataset.artifact_ids == ("item-9", "item-10") and dataset.response_excerpt == "items=2"
    rollback = client.execute("rollback_prompt", {"name": "p", "version": 1, "text": "v2-text"})
    assert rollback.status == "ok"  # recreate-as-latest verified: get_prompt returns the same text
    scored = client.execute("score_agent_trace", {"trace_id": "trace-1"})
    assert scored.status == "ok"
    compare = client.execute("compare_runs", {"name": "d"})
    assert compare.status == "ok"
    urls = [url for _method, url, _headers, _body in rest.calls]
    assert any("/experiments?datasetId=ds-1&size=10" in url for url in urls)
    client.close()


# --------------------------------------------------- opik guarded-chain branches
def _opik_client(
    handle: Any,
    rest: FakeRest | None = None,
    judge: JudgeSpec | None = JUDGE,
    judge_api_key: str = "",
) -> Any:
    from backend_validation.clients.opik import OpikProbeClient

    return OpikProbeClient(
        handle,
        base_url="http://opik",
        auth={"Comet-Workspace": "default"},
        rest=rest if rest is not None else FakeRest(),
        judge=judge,
        judge_api_key=judge_api_key,
    )


def test_opik_fetch_otel_trace_searches_by_span_name() -> None:
    handle = _FakeOpikHandle()
    found = _opik_client(handle).execute("fetch_otel_trace", {"span_name": "bv-otlp-m1", "trace_id": "beef" * 8})
    assert found.status == "ok" and found.artifact_ids == ("trace-otel-1",)
    assert "matches=1" in found.response_excerpt
    assert handle.searches == ['name contains "bv-otlp-m1"']  # span_name wins over the OTLP hex id
    fallback = _FakeOpikHandle()
    _opik_client(fallback).execute("fetch_otel_trace", {"trace_id": "beef" * 8})
    assert fallback.searches == [f'name contains "{"beef" * 8}"']  # langfuse-shaped payloads still work


def test_opik_fetch_otel_trace_empty_and_unsearchable_are_errors() -> None:
    class _EmptySearch(_FakeOpikHandle):
        def search_traces(self, *, filter_string: str) -> list[Any]:
            return []

    empty = _opik_client(_EmptySearch()).execute("fetch_otel_trace", {"span_name": "bv"})
    assert empty.status == "error" and "matches=0" in empty.response_excerpt
    assert "retryable" in empty.stderr  # the runner retries fetches: OTLP ingest-lag tolerance
    bare = _opik_client(_BareOpikHandle()).execute("fetch_otel_trace", {"span_name": "bv"})
    assert bare.status == "error" and "search unavailable" in bare.response_excerpt


def test_opik_rollback_prompt_requires_text_and_verifies_latest() -> None:
    handle = _FakeOpikHandle()
    client = _opik_client(handle)
    missing = client.execute("rollback_prompt", {"name": "p", "version": 1})
    assert missing.status == "error" and "text" in missing.response_excerpt
    assert handle.prompts == []  # nothing created for an unverifiable request
    ok = client.execute("rollback_prompt", {"name": "p", "version": 1, "text": "v2-text"})
    assert ok.status == "ok" and handle.prompts == [{"name": "p", "prompt": "v2-text"}]
    mismatch = client.execute("rollback_prompt", {"name": "p", "text": "v1"})
    assert mismatch.status == "error" and "unverified" in mismatch.response_excerpt


def test_opik_none_prompt_is_an_error_not_a_success() -> None:
    class _NoPrompt(_FakeOpikHandle):
        def get_prompt(self, **_kwargs: Any) -> _FakeOpikPrompt | None:
            return None  # the SDK's 404 shape: None, not an exception

    client = _opik_client(_NoPrompt())
    fetched = client.execute("fetch_prompt", {"name": "p"})
    assert fetched.status == "error" and "not found" in fetched.response_excerpt
    rolled = client.execute("rollback_prompt", {"name": "p", "text": "v1"})
    assert rolled.status == "error" and "unverified" in rolled.response_excerpt


def test_opik_link_dataset_run_creates_experiment_and_links_item() -> None:
    handle = _FakeOpikHandle()
    linked = _opik_client(handle).execute(
        "link_dataset_run", {"name": "d", "run_name": "r", "item_id": "i-1", "trace_id": "t-1"}
    )
    assert linked.status == "ok" and linked.artifact_ids == ("exp-1",)
    assert "item_linked=True" in linked.response_excerpt
    (references,) = handle.experiments[0].inserted
    assert references == [{"dataset_item_id": "i-1", "trace_id": "t-1"}]  # SDK-less env: dict wire shape
    assert handle.flushed == 1  # experiment items deliver async; flush before reporting


def test_opik_link_dataset_run_uses_sdk_reference_class_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Refs:
        def __init__(self, *, dataset_item_id: str, trace_id: str) -> None:
            self.dataset_item_id = dataset_item_id
            self.trace_id = trace_id

    opik_module = types.ModuleType("opik")
    opik_module.ExperimentItemReferences = _Refs  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    handle = _FakeOpikHandle()
    outcome = _opik_client(handle).execute(
        "create_experiment_run", {"name": "d", "run_name": "r", "item_id": "i-1", "trace_id": "t-1"}
    )
    assert outcome.status == "ok"
    (references,) = handle.experiments[0].inserted
    assert isinstance(references[0], _Refs) and references[0].dataset_item_id == "i-1"


def test_opik_link_dataset_run_without_ids_or_insert_support() -> None:
    handle = _FakeOpikHandle()
    partial = _opik_client(handle).execute("link_dataset_run", {"name": "d", "run_name": "r"})
    assert partial.status == "ok" and "item_linked=False" in partial.response_excerpt
    assert handle.experiments[0].inserted == []

    class _InsertlessExperiment(_FakeOpikHandle):
        def create_experiment(self, **_kwargs: Any) -> Any:
            return types.SimpleNamespace(id="exp-2")  # pre-insert SDK Experiment shape

    outcome = _opik_client(_InsertlessExperiment()).execute(
        "link_dataset_run", {"name": "d", "run_name": "r", "item_id": "i", "trace_id": "t"}
    )
    assert outcome.status == "ok" and "item_linked=False" in outcome.response_excerpt
    assert outcome.artifact_ids == ("exp-2",)


def test_opik_compare_runs_missing_dataset_is_an_error() -> None:
    class _RaisingDataset(_FakeOpikHandle):
        def get_dataset(self, _name: str) -> _FakeOpikDataset:
            raise KeyError("no such dataset")

    outcome = _opik_client(_RaisingDataset()).execute("compare_runs", {"name": "ghost"})
    assert outcome.status == "error" and "KeyError" in outcome.stderr


CONTAINER_JUDGE = JudgeSpec(
    base_url="http://127.0.0.1:18323/v1",
    model="m",
    api_key_env="BV_JUDGE_API_KEY",
    container_base_url="http://host.docker.internal:18323/v1",
)


def test_opik_configure_judge_arms_rule_via_fern_chain() -> None:
    handle = _FakeOpikHandle()
    client = _opik_client(handle, judge=CONTAINER_JUDGE, judge_api_key="jk")
    configured = client.execute("configure_judge", {"judge_url": CONTAINER_JUDGE.base_url})
    assert configured.status == "ok"
    assert "evaluator=bv-judge-rule" in configured.response_excerpt
    assert "provider=custom-llm" in configured.response_excerpt  # full-kwargs tier succeeded
    assert handle.rest_client.projects.retrieved == ["Default Project"]
    (stored,) = handle.rest_client.llm_provider_key.stored
    # Server-side evaluators dial from INSIDE the backend container: container URL, not loopback.
    assert stored == {
        "provider": "custom-llm",
        "provider_name": "bv-local-judge",
        "base_url": "http://host.docker.internal:18323/v1",
        "api_key": "jk",
    }
    (rule,) = handle.rest_client.automation_rule_evaluators.requests
    assert rule["type"] == "llm_as_judge" and rule["sampling_rate"] == 1.0
    assert rule["project_id"] == "proj-1" and rule["action"] == "evaluator"
    assert rule["code"]["schema"][0]["type"] == "BOOLEAN"
    assert rule["code"]["model"]["name"] == "m"


def test_opik_configure_judge_omits_absent_api_key_and_honors_handle_project() -> None:
    handle = _FakeOpikHandle()
    handle.project_name = "bv-project"  # type: ignore[attr-defined]  # 1.11.x property shape
    client = _opik_client(handle, judge=JUDGE)
    assert client.execute("configure_judge", {}).status == "ok"
    (stored,) = handle.rest_client.llm_provider_key.stored
    # api_key is ALWAYS supplied (older fern generations require it); the placeholder
    # stands in for an unauthenticated local judge.
    assert stored["api_key"] == "unused"
    assert stored["base_url"] == JUDGE.base_url  # empty container_base_url falls back to base_url
    assert handle.rest_client.projects.retrieved == ["bv-project"]


def test_opik_configure_judge_rest_fallback_and_unarmed_eval() -> None:
    rest = FakeRest(status_code=404, body="not found")
    client = _opik_client(_BareOpikHandle(), rest=rest, judge=None)
    fallback = client.execute("configure_judge", {"judge_url": "http://j"})
    assert fallback.status == "error" and "HTTP 404" in fallback.response_excerpt
    method, url, _headers, body = rest.calls[0]
    assert method == "POST" and url.endswith("/api/v1/private/automations/evaluators")
    assert body == {"model": {"baseUrl": "http://j"}}
    unarmed = client.execute("run_judge_eval", {"trace_id": "t-1"})
    assert unarmed.status == "error" and "no armed judge rule" in unarmed.response_excerpt


def test_opik_run_judge_eval_creates_trigger_trace_in_armed_project() -> None:
    handle = _FakeOpikHandle()
    client = _opik_client(handle, judge=JUDGE)
    assert client.execute("configure_judge", {}).status == "ok"
    outcome = client.execute("run_judge_eval", {"trace_id": "t-9"})
    assert outcome.status == "ok" and outcome.artifact_ids == ("trace-1",)
    assert "trace=trace-1" in outcome.response_excerpt
    (trace_kwargs,) = handle.traces
    assert trace_kwargs["project_name"] == "Default Project"  # the armed rule's project
    assert trace_kwargs["name"] == "bv-judge-eval-t-9"
    # Same id as the probe's trace so fetch_judge_scores polls the SCORED trace, and
    # real input/output fields so the rule's {{input}}/{{output}} variables map onto
    # something the evaluator can actually judge (empty traces score nothing).
    assert trace_kwargs["id"] == "t-9"
    assert trace_kwargs["input"] and trace_kwargs["output"]
    assert handle.flushed == 1  # the arriving trace IS the online rule's trigger


def test_opik_fetch_judge_scores_empty_vs_present() -> None:
    present = _opik_client(_FakeOpikHandle()).execute("fetch_judge_scores", {"trace_id": "t-1"})
    assert present.status == "ok" and "scores=1" in present.response_excerpt

    class _ScoresLess(_FakeOpikHandle):
        def get_trace_content(self, id: str) -> Any:
            return types.SimpleNamespace(name="bv")  # no feedback_scores field at all

    empty = _opik_client(_ScoresLess()).execute("fetch_agent_scores", {"trace_id": "t-1"})
    assert empty.status == "error" and "scores=0" in empty.response_excerpt
    assert "retryable" in empty.stderr  # server-side scoring lag; the runner retries fetches


def _install_rag_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    value: float = 0.83,
    scoring_failed: bool = False,
    recorder: dict[str, Any] | None = None,
    with_classes: bool = True,
) -> None:
    """sys.modules stub for ``from opik.evaluation import metrics, models`` (repo convention)."""
    record = recorder if recorder is not None else {}

    class _StubModel:
        def __init__(self, **kwargs: Any) -> None:
            record["model_kwargs"] = kwargs

    class _StubMetric:
        def __init__(self, **kwargs: Any) -> None:
            record["metric_kwargs"] = kwargs

        def score(self, **kwargs: Any) -> Any:
            record["score_kwargs"] = kwargs
            return types.SimpleNamespace(value=value, scoring_failed=scoring_failed)

    opik_module = types.ModuleType("opik")
    evaluation = types.ModuleType("opik.evaluation")
    metrics_module = types.ModuleType("opik.evaluation.metrics")
    models_module = types.ModuleType("opik.evaluation.models")
    if with_classes:
        metrics_module.AnswerRelevance = _StubMetric  # type: ignore[attr-defined]
        models_module.LiteLLMChatModel = _StubModel  # type: ignore[attr-defined]
    evaluation.metrics = metrics_module  # type: ignore[attr-defined]
    evaluation.models = models_module  # type: ignore[attr-defined]
    opik_module.evaluation = evaluation  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    monkeypatch.setitem(sys.modules, "opik.evaluation", evaluation)
    monkeypatch.setitem(sys.modules, "opik.evaluation.metrics", metrics_module)
    monkeypatch.setitem(sys.modules, "opik.evaluation.models", models_module)


_RAG_PAYLOAD: dict[str, object] = {
    "question": "sky color?",
    "contexts": ["the sky is blue"],
    "answer": "Blue.",
    "judge_url": "http://j",
}


def test_opik_run_rag_metric_emits_parseable_score_token(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}
    _install_rag_stub(monkeypatch, value=0.83, recorder=recorded)
    outcome = _opik_client(_FakeOpikHandle(), judge_api_key="jk").execute("run_rag_metric", _RAG_PAYLOAD)
    assert outcome.status == "ok"
    assert "score=0.83" in outcome.response_excerpt  # parsed_score_in_unit_range needs this token
    # The SDK-side metric dials the HOST-visible judge; litellm needs the provider prefix.
    assert recorded["model_kwargs"] == {"model_name": "openai/m", "base_url": JUDGE.base_url, "api_key": "jk"}
    assert recorded["metric_kwargs"]["track"] is False  # keep metric traffic out of the traces under test
    assert recorded["score_kwargs"] == {"input": "sky color?", "output": "Blue.", "context": ["the sky is blue"]}


def test_opik_run_rag_metric_error_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_rag_stub(monkeypatch, scoring_failed=True)
    failed = _opik_client(_FakeOpikHandle()).execute("run_rag_metric", _RAG_PAYLOAD)
    assert failed.status == "error" and "scoring_failed" in failed.response_excerpt
    no_judge = _opik_client(_FakeOpikHandle(), judge=None).execute("run_rag_metric", _RAG_PAYLOAD)
    assert no_judge.status == "error" and "no judge" in no_judge.response_excerpt


def test_opik_run_rag_metric_degrades_without_metric_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    no_sdk = _opik_client(_FakeOpikHandle()).execute("run_rag_metric", _RAG_PAYLOAD)
    assert no_sdk.status == "error" and "unavailable" in no_sdk.response_excerpt
    _install_rag_stub(monkeypatch, with_classes=False)  # modules import but the classes are absent
    no_classes = _opik_client(_FakeOpikHandle()).execute("run_rag_metric", _RAG_PAYLOAD)
    assert no_classes.status == "error" and "unavailable" in no_classes.response_excerpt


class _StubApiError(Exception):
    """Duck-typed fern ApiError: carries status_code/body like opik.rest_api.core.api_error."""

    def __init__(self, status_code: int, body: object) -> None:
        super().__init__(f"status_code: {status_code}")
        self.status_code = status_code
        self.body = body


def _install_guardrails_stub(
    monkeypatch: pytest.MonkeyPatch,
    validate: Callable[[str], Any],
    with_class: bool = True,
) -> dict[str, Any]:
    record: dict[str, Any] = {}

    class _StubGuardrailsClient:
        def __init__(self, *, httpx_client: Any, host_url: str) -> None:
            record["host_url"] = host_url

        def validate(self, text: str, validations: list[dict[str, Any]]) -> Any:
            record["text"] = text
            record["validations"] = validations
            return validate(text)

    opik_module = types.ModuleType("opik")
    guardrails = types.ModuleType("opik.guardrails")
    rest_module = types.ModuleType("opik.guardrails.rest_api_client")
    if with_class:
        rest_module.GuardrailsApiClient = _StubGuardrailsClient  # type: ignore[attr-defined]
    guardrails.rest_api_client = rest_module  # type: ignore[attr-defined]
    opik_module.guardrails = guardrails  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    monkeypatch.setitem(sys.modules, "opik.guardrails", guardrails)
    monkeypatch.setitem(sys.modules, "opik.guardrails.rest_api_client", rest_module)
    return record


def test_opik_invoke_guardrail_via_sdk_builds_official_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_validation.probes import structured

    record = _install_guardrails_stub(monkeypatch, lambda _text: types.SimpleNamespace(validation_passed=True))
    outcome = _opik_client(_FakeOpikHandle()).execute("invoke_guardrail", {"text": "my SSN is 000-00-0000"})
    assert outcome.status == "ok"
    assert outcome.response_excerpt.startswith('HTTP 200: {"validation_passed": true}')
    assert structured(outcome.response_excerpt)  # guardrail_verdict_returned relies on this shape
    assert record["host_url"] == "http://opik/guardrails/"  # config.guardrails_backend_host shape
    assert record["validations"][0]["type"] == "PII"


def test_opik_invoke_guardrail_maps_api_errors_and_reraises_others(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_api(_text: str) -> Any:
        raise _StubApiError(status_code=422, body={"error": "bad"})

    _install_guardrails_stub(monkeypatch, _raise_api)
    outcome = _opik_client(_FakeOpikHandle()).execute("invoke_guardrail", {"text": "x"})
    assert outcome.status == "error" and outcome.response_excerpt.startswith("HTTP 422:")
    assert outcome.stderr == "http_status=422"

    def _raise_plain(_text: str) -> Any:
        raise RuntimeError("guardrails backend unreachable")

    _install_guardrails_stub(monkeypatch, _raise_plain)
    crashed = _opik_client(_FakeOpikHandle()).execute("invoke_guardrail", {"text": "x"})
    assert crashed.status == "error" and "RuntimeError" in crashed.stderr  # dispatch captured the raise


def test_opik_invoke_guardrail_rest_fallback_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    rest = FakeRest()
    outcome = _opik_client(_FakeOpikHandle(), rest=rest).execute("invoke_guardrail", {"text": "probe"})
    assert outcome.status == "ok"
    method, url, headers, body = rest.calls[0]
    assert method == "POST" and url == "http://opik/guardrails/api/v1/guardrails/validations"
    assert headers == {"Comet-Workspace": "default"}
    assert body is not None and body["text"] == "probe"
    # Class absent or httpx absent inside the guard -> the same verified-REST fallback.
    _install_guardrails_stub(monkeypatch, lambda _text: None, with_class=False)
    classless = FakeRest()
    assert _opik_client(_FakeOpikHandle(), rest=classless).execute("invoke_guardrail", {}).status == "ok"
    assert classless.calls
    record = _install_guardrails_stub(monkeypatch, lambda _text: types.SimpleNamespace(validation_passed=True))
    monkeypatch.setitem(sys.modules, "httpx", None)  # import -> ImportError
    no_httpx = FakeRest()
    assert _opik_client(_FakeOpikHandle(), rest=no_httpx).execute("invoke_guardrail", {}).status == "ok"
    assert no_httpx.calls and "host_url" not in record  # the SDK client was never constructed


def test_opik_annotation_chain_high_level_and_fern_submit() -> None:
    handle = _FakeOpikHandle()
    client = _opik_client(handle)
    created = client.execute("create_annotation_queue", {"name": "bv-queue"})
    assert created.status == "ok" and created.artifact_ids == ("queue-1",)
    assert handle.queues == ["bv-queue"]
    submitted = client.execute("submit_annotation_score", {"queue_id": "queue-1", "trace_id": "t-1"})
    assert submitted.status == "ok"
    assert handle.rest_client.annotation_queues.added == [("queue-1", ["t-1"])]
    fetched = client.execute("fetch_annotations", {})
    assert fetched.status == "ok" and fetched.response_excerpt == "queues=1"


def test_opik_annotation_queue_fern_branch_mints_uuid7() -> None:
    class _FernOnly(_FakeOpikHandle):
        create_traces_annotation_queue = None  # type: ignore[assignment]
        get_traces_annotation_queues = None  # type: ignore[assignment]

    handle = _FernOnly()
    client = _opik_client(handle)
    created = client.execute("create_annotation_queue", {"name": "bv-queue"})
    assert created.status == "ok"
    (kwargs,) = handle.rest_client.annotation_queues.created
    assert kwargs["project_id"] == "proj-1" and kwargs["scope"] == "trace" and kwargs["name"] == "bv-queue"
    minted = uuid.UUID(str(kwargs["id"]))  # fern create returns 201/None: the id must be client-minted
    assert minted.version == 7 and created.artifact_ids == (str(minted),)
    fetched = client.execute("fetch_annotations", {})
    assert fetched.status == "ok" and fetched.response_excerpt == "queues=1"  # fern find path


def test_opik_annotation_rest_fallback_and_failed_create() -> None:
    rest = FakeRest()
    client = _opik_client(_BareOpikHandle(), rest=rest)
    created = client.execute("create_annotation_queue", {"name": "bv-queue"})
    assert created.status == "ok" and len(created.artifact_ids) == 1
    method, url, _headers, body = rest.calls[0]
    assert method == "POST" and url.endswith("/api/v1/private/annotation-queues")
    assert body is not None and uuid.UUID(str(body["id"])).version == 7 and body["scope"] == "trace"
    submitted = client.execute("submit_annotation_score", {"queue_id": "q-9", "trace_id": "t-1"})
    assert submitted.status == "ok"
    _method2, url2, _headers2, body2 = rest.calls[1]
    assert url2.endswith("/annotation-queues/q-9/items/add") and body2 == {"ids": ["t-1"]}
    fetched = client.execute("fetch_annotations", {})
    assert fetched.status == "ok" and rest.calls[2][1].endswith("/api/v1/private/annotation-queues")
    failed = _opik_client(_BareOpikHandle(), rest=FakeRest(status_code=500, body="boom"))
    unmade = failed.execute("create_annotation_queue", {"name": "bv-queue"})
    assert unmade.status == "error" and unmade.artifact_ids == ()  # no minted id for a failed create


def test_opik_fetch_annotations_empty_states_are_retryable_errors() -> None:
    class _EmptyQueues(_FakeOpikHandle):
        def get_traces_annotation_queues(self) -> list[Any]:
            return []

    empty_high = _opik_client(_EmptyQueues()).execute("fetch_annotations", {})
    assert empty_high.status == "error" and "queues=0" in empty_high.response_excerpt

    class _EmptyFern(_FakeOpikHandle):
        create_traces_annotation_queue = None  # type: ignore[assignment]
        get_traces_annotation_queues = None  # type: ignore[assignment]

        def __init__(self) -> None:
            super().__init__()
            self.rest_client.annotation_queues = _FakeFernQueues(existing=0)

    empty_fern = _opik_client(_EmptyFern()).execute("fetch_annotations", {})
    assert empty_fern.status == "error" and "queues=0" in empty_fern.response_excerpt


def test_opik_alert_rule_fern_chain_and_webhook_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeOpikHandle()
    client = _opik_client(handle)
    created = client.execute("create_alert_rule", {"name": "bv-alert-m1"})
    assert created.status == "ok" and created.artifact_ids == ("bv-alert-m1",)
    (kwargs,) = handle.rest_client.alerts.created
    assert kwargs["name"] == "bv-alert-m1"
    assert kwargs["webhook"] == {"url": "http://127.0.0.1:9/bv-sink"}  # SDK-less env: mapping shape

    class _WebhookWrite:
        def __init__(self, *, url: str) -> None:
            self.url = url

    opik_module = types.ModuleType("opik")
    rest_api = types.ModuleType("opik.rest_api")
    types_module = types.ModuleType("opik.rest_api.types")
    types_module.WebhookWrite = _WebhookWrite  # type: ignore[attr-defined]
    rest_api.types = types_module  # type: ignore[attr-defined]
    opik_module.rest_api = rest_api  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    monkeypatch.setitem(sys.modules, "opik.rest_api", rest_api)
    monkeypatch.setitem(sys.modules, "opik.rest_api.types", types_module)
    assert client.execute("create_alert_rule", {}).status == "ok"
    typed = handle.rest_client.alerts.created[1]["webhook"]
    assert isinstance(typed, _WebhookWrite) and typed.url == "http://127.0.0.1:9/bv-sink"
    verified = client.execute("verify_alert_rule", {})
    assert verified.status == "ok" and verified.response_excerpt == "alerts=1"


def test_opik_alert_rest_fallback_and_empty_find() -> None:
    rest = FakeRest()
    client = _opik_client(_BareOpikHandle(), rest=rest)
    assert client.execute("create_alert_rule", {"name": "a"}).status == "ok"
    assert client.execute("verify_alert_rule", {}).status == "ok"
    urls = [url for _method, url, _headers, _body in rest.calls]
    assert urls == ["http://opik/api/v1/private/alerts", "http://opik/api/v1/private/alerts"]

    class _NoAlerts(_FakeOpikHandle):
        def __init__(self) -> None:
            super().__init__()
            self.rest_client.alerts = _FakeFernAlerts(existing=0)

    empty = _opik_client(_NoAlerts()).execute("verify_alert_rule", {})
    assert empty.status == "error" and empty.response_excerpt == "alerts=0"


def test_opik_otlp_export_defaults_body_and_carries_workspace_header() -> None:
    rest = FakeRest()
    outcome = _opik_client(_FakeOpikHandle(), rest=rest).execute("otlp_export", {})
    assert outcome.status == "ok"
    _method, url, headers, body = rest.calls[0]
    assert url.endswith("/api/v1/private/otel/v1/traces")
    assert headers == {"Comet-Workspace": "default"} and body == {"resourceSpans": []}


def test_opik_from_spec_workspace_header_and_judge_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_validation.clients.opik import OpikProbeClient

    recorded: dict[str, Any] = {}

    def _factory(**kwargs: Any) -> _FakeOpikHandle:
        recorded.update(kwargs)
        return _FakeOpikHandle()

    opik_module = types.ModuleType("opik")
    opik_module.Opik = _factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opik", opik_module)
    spec = _spec("opik", {"api_key": "BV_OPIK_KEY"})
    client = OpikProbeClient.from_spec(spec, judge=JUDGE, env={"BV_OPIK_KEY": "k", "BV_JUDGE_API_KEY": "jk"})
    assert recorded == {"host": "http://127.0.0.1:1/api", "api_key": "k", "workspace": "default"}
    assert client._auth == {"Comet-Workspace": "default", "Authorization": "k"}  # raw key, no Bearer
    assert client._judge_api_key == "jk"
    keyless = OpikProbeClient.from_spec(spec.model_copy(update={"workspace": "team-a"}), env={})
    assert recorded["api_key"] is None and recorded["workspace"] == "team-a"
    assert keyless._auth == {"Comet-Workspace": "team-a"}  # no Authorization without a key
    assert keyless._judge_api_key == ""
    keyless.close()  # rich handle: flush() exists and runs
    _opik_client(types.SimpleNamespace()).close()  # flush-less handle: close is a no-op


# --------------------------------------------------------------- shared helpers
def test_draft_from_rest_pins_the_shared_excerpt_format() -> None:
    ok = draft_from_rest(RestResult(status_code=200, body_excerpt='{"a": 1}'))
    assert ok.status == "ok" and ok.response_excerpt == 'HTTP 200: {"a": 1}' and ok.stderr == ""
    error = draft_from_rest(RestResult(status_code=404, body_excerpt="nope"))
    assert error.status == "error" and error.response_excerpt == "HTTP 404: nope"
    assert error.stderr == "http_status=404"  # evidentiary only; no rubric predicate reads it
    long = draft_from_rest(RestResult(status_code=200, body_excerpt="x" * 300))
    assert len(long.response_excerpt) == 220  # the truncation boundary is part of the format


def test_uuid7_version_variant_and_timestamp_layout() -> None:
    value = uuid7(now_ms=lambda: 0x0123456789AB, rand_bytes=lambda count: b"\x00" * count)
    assert value.version == 7 and value.variant == uuid.RFC_4122
    assert value.int >> 80 == 0x0123456789AB  # 48-bit unix-ms prefix, bit-exact


def test_uuid7_is_time_ordered_and_defaults_work() -> None:
    earlier = uuid7(now_ms=lambda: 1, rand_bytes=lambda count: b"\xff" * count)
    later = uuid7(now_ms=lambda: 2, rand_bytes=lambda count: b"\x00" * count)
    assert earlier < later  # the timestamp prefix dominates every random bit
    assert uuid7().version == 7  # real clock + urandom path


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


def test_opik_configure_judge_retries_provider_key_on_older_fern_signature() -> None:
    # Older fern generations reject provider_name (and require api_key): the first call
    # TypeErrors and the compat retry with the universal subset must still arm the rule
    # (CodeRabbit review).
    handle = _FakeOpikHandle()

    original = handle.rest_client.llm_provider_key.store_llm_provider_api_key

    def _old_signature(**kwargs: Any) -> None:
        if "provider_name" in kwargs:
            raise TypeError("store_llm_provider_api_key() got an unexpected keyword argument 'provider_name'")
        original(**kwargs)

    handle.rest_client.llm_provider_key.store_llm_provider_api_key = _old_signature  # type: ignore[method-assign]
    client = _opik_client(handle, judge=JUDGE)
    configured = client.execute("configure_judge", {})
    assert configured.status == "ok"
    assert "provider=custom-llm-compat" in configured.response_excerpt
    (stored,) = handle.rest_client.llm_provider_key.stored
    assert stored == {"provider": "custom-llm", "api_key": "unused", "base_url": JUDGE.base_url}
    assert handle.rest_client.automation_rule_evaluators.requests  # rule still armed
    assert client.execute("run_judge_eval", {"trace_id": "t-1"}).status == "ok"
