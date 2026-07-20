"""Opik probe client: thin operations over the pinned SDK plus raw REST attempts.

Same contract as the Langfuse client: bodies are best-effort against the pinned SDK minor
(``opik>=1.7,<2``) and the private HTTP API of the self-hosted stack; anything that no
longer matches degrades to an ``error``/``unsupported`` observable. Self-hosted Opik runs
without authentication by default, so a missing API key is tolerated (empty headers), not
an init failure — the opposite of Langfuse, which hard-requires its key pair.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend_validation.clients._dispatch import DispatchProbeClient, OpDraft, OpHandler
from backend_validation.clients._rest import RestResult, RestTransport, UrllibRest
from backend_validation.settings import BackendSpec, JudgeSpec

_API = "/api/v1/private"


def _draft(result: RestResult) -> OpDraft:
    status = "ok" if result.ok else "error"
    return OpDraft(status=status, response_excerpt=f"HTTP {result.status_code}: {result.body_excerpt}"[:220])


class OpikProbeClient(DispatchProbeClient):
    backend_id = "opik"
    idempotent_operations = frozenset(
        {
            "fetch_trace",
            "fetch_otel_trace",
            "fetch_prompt",
            "fetch_dataset",
            "fetch_judge_scores",
            "fetch_agent_scores",
            "compare_runs",
            "diff_runs",
            "verify_alert_rule",
            "fetch_annotations",
        }
    )

    def __init__(
        self,
        handle: Any,
        *,
        base_url: str,
        auth: dict[str, str],
        rest: RestTransport | None = None,
        judge: JudgeSpec | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._handle = handle
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._rest: RestTransport = rest if rest is not None else UrllibRest()
        self._judge = judge
        self._timeout = timeout

    @classmethod
    def from_spec(
        cls,
        spec: BackendSpec,
        *,
        judge: JudgeSpec | None = None,
        env: Mapping[str, str] | None = None,
    ) -> OpikProbeClient:
        import os

        resolved_env = env if env is not None else os.environ
        api_key = resolved_env.get(spec.credential_env.get("api_key", ""), "")
        import opik

        handle = opik.Opik(host=f"{spec.base_url}/api", api_key=api_key or None)
        auth = {"Authorization": api_key} if api_key else {}
        return cls(handle, base_url=spec.base_url, auth=auth, judge=judge)

    def close(self) -> None:
        flush = getattr(self._handle, "flush", None)
        if callable(flush):
            flush()

    def _get(self, path: str) -> OpDraft:
        return _draft(self._rest.call("GET", self._base_url + path, headers=self._auth, timeout=self._timeout))

    def _post(self, path: str, body: dict[str, object]) -> OpDraft:
        result = self._rest.call(
            "POST", self._base_url + path, headers=self._auth, json_body=body, timeout=self._timeout
        )
        return _draft(result)

    # ----------------------------------------------------------- SDK operations
    def _op_create_trace(self, payload: Mapping[str, object]) -> OpDraft:
        trace = self._handle.trace(name=str(payload.get("name", "bv-probe")))
        self._handle.flush()
        return OpDraft(artifact_ids=(str(trace.id),))

    def _op_fetch_trace(self, payload: Mapping[str, object]) -> OpDraft:
        content = self._handle.get_trace_content(id=str(payload["trace_id"]))
        return OpDraft(artifact_ids=(str(payload["trace_id"]),), response_excerpt=f"name={content.name}")

    def _op_fetch_otel_trace(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_fetch_trace(payload)

    def _op_create_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.create_prompt(name=str(payload["name"]), prompt=str(payload.get("text", "v1")))
        return OpDraft(artifact_ids=(str(payload["name"]),), response_excerpt=f"commit={prompt.commit}")

    def _op_create_prompt_version(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_create_prompt({**payload, "text": str(payload.get("text", "v2"))})

    def _op_fetch_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.get_prompt(name=str(payload["name"]))
        return OpDraft(response_excerpt=f"commit={prompt.commit} prompt={str(prompt.prompt)[:80]}")

    def _op_rollback_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        commit = str(payload.get("commit", ""))
        prompt = self._handle.get_prompt(name=str(payload["name"]), commit=commit or None)
        return OpDraft(response_excerpt=f"rolled-back-view commit={prompt.commit}")

    def _op_create_dataset(self, payload: Mapping[str, object]) -> OpDraft:
        self._handle.get_or_create_dataset(name=str(payload["name"]))
        return OpDraft(artifact_ids=(str(payload["name"]),))

    def _op_insert_dataset_items(self, payload: Mapping[str, object]) -> OpDraft:
        dataset = self._handle.get_or_create_dataset(name=str(payload["name"]))
        count = int(str(payload.get("count", 2)))
        dataset.insert([{"q": f"item-{index}", "expected": f"a-{index}"} for index in range(count)])
        return OpDraft(response_excerpt=f"inserted={count}")

    def _op_fetch_dataset(self, payload: Mapping[str, object]) -> OpDraft:
        dataset = self._handle.get_or_create_dataset(name=str(payload["name"]))
        items = list(dataset.get_items())
        item_ids = tuple(str(item.get("id", "")) for item in items[:3] if isinstance(item, dict))
        return OpDraft(artifact_ids=item_ids, response_excerpt=f"items={len(items)}")

    def _op_score_agent_trace(self, payload: Mapping[str, object]) -> OpDraft:
        self._handle.log_traces_feedback_scores(
            [{"id": str(payload["trace_id"]), "name": "task_success", "value": 1.0}]
        )
        self._handle.flush()
        return OpDraft(artifact_ids=(str(payload["trace_id"]),))

    def _op_create_agent_trace(self, payload: Mapping[str, object]) -> OpDraft:
        trace = self._handle.trace(name=str(payload.get("name", "bv-agent")))
        trace.span(name="tool:search", type="tool").end()
        trace.span(name="tool:calc", type="tool").end()
        self._handle.flush()
        return OpDraft(artifact_ids=(str(trace.id),), response_excerpt="spans=2")

    # ---------------------------------------------------------- REST operations
    def _op_otlp_export(self, payload: Mapping[str, object]) -> OpDraft:
        body = payload.get("otlp_body")
        result = self._rest.call(
            "POST",
            f"{self._base_url}{_API}/otel/v1/traces",
            headers=self._auth,
            json_body=body if isinstance(body, dict) else {"resourceSpans": []},
            timeout=self._timeout,
        )
        return _draft(result)

    def _op_link_dataset_run(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"{_API}/experiments?datasetName={payload.get('name', '')}")

    def _op_configure_judge(self, payload: Mapping[str, object]) -> OpDraft:
        judge_url = self._judge.base_url if self._judge else str(payload.get("judge_url", ""))
        return self._post(f"{_API}/automations/evaluators", {"model": {"baseUrl": judge_url}})

    def _op_run_judge_eval(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/automations/evaluators/run", {"traceId": str(payload.get("trace_id", ""))})

    def _op_run_rag_metric(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/evaluators/rag", dict(payload))

    def _op_fetch_judge_scores(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"{_API}/traces/{payload.get('trace_id', '')}/feedback-scores")

    def _op_fetch_agent_scores(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_fetch_judge_scores(payload)

    def _op_create_experiment_run(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(
            f"{_API}/experiments",
            {"name": str(payload.get("run_name", "bv-run")), "datasetName": str(payload.get("name", ""))},
        )

    def _op_compare_runs(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"{_API}/experiments?datasetName={payload.get('name', '')}")

    def _op_diff_runs(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_compare_runs(payload)

    def _op_invoke_guardrail(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/guardrails/validations", {"input": str(payload.get("text", "probe"))})

    def _op_create_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/alerts", {"name": "bv-alert"})

    def _op_verify_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"{_API}/alerts")

    def _op_create_annotation_queue(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/annotation-queues", {"name": str(payload.get("name", "bv-queue"))})

    def _op_submit_annotation_score(self, payload: Mapping[str, object]) -> OpDraft:
        queue = payload.get("queue_id", "bv-queue")
        return self._post(f"{_API}/annotation-queues/{queue}/items", {"traceId": str(payload.get("trace_id", ""))})

    def _op_fetch_annotations(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"{_API}/annotation-queues")

    def _op_invoke_redteam(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/redteam/run", {"target": "probe"})

    def _op_probe_endpoint(self, payload: Mapping[str, object]) -> OpDraft:
        result = self._rest.call("GET", str(payload["url"]), timeout=min(self._timeout, 5.0))
        return _draft(result)

    def _ops(self) -> Mapping[str, OpHandler]:
        return {name.removeprefix("_op_"): getattr(self, name) for name in dir(self) if name.startswith("_op_")}
