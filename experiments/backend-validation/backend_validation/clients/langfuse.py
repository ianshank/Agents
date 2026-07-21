"""Langfuse probe client: thin operations over the pinned SDK plus raw REST attempts.

Operation bodies are best-effort against the pinned SDK minor (``langfuse>=2``) and the
documented public HTTP API. That is deliberate: an operation that no longer matches the
surface degrades to an ``error``/``unsupported`` OBSERVABLE (captured by the dispatch
base), which is exactly the evidence the matrix validation wants — review these bodies
against the deployed version during P0 sign-off, not at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend_validation.clients import DEFAULT_OP_TIMEOUT_SECONDS, MissingCredentialsError
from backend_validation.clients._dispatch import DispatchProbeClient, OpDraft, OpHandler
from backend_validation.clients._rest import RestResult, RestTransport, UrllibRest, basic_auth_header
from backend_validation.settings import BackendSpec, JudgeSpec

_OTLP_PATH = "/api/public/otel/v1/traces"


def _draft(result: RestResult) -> OpDraft:
    status = "ok" if result.ok else "error"
    return OpDraft(status=status, response_excerpt=f"HTTP {result.status_code}: {result.body_excerpt}"[:220])


class LangfuseProbeClient(DispatchProbeClient):
    backend_id = "langfuse"
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
        timeout: float = DEFAULT_OP_TIMEOUT_SECONDS,
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
        op_timeout: float | None = None,
    ) -> LangfuseProbeClient:
        import os

        resolved_env = env if env is not None else os.environ
        secret = resolved_env.get(spec.credential_env.get("secret_key", ""), "")
        public = resolved_env.get(spec.credential_env.get("public_key", ""), "")
        if not secret or not public:
            names = sorted(spec.credential_env.values())
            raise MissingCredentialsError(f"langfuse credentials missing; set env vars {names} (see .env.example)")
        import langfuse

        handle = langfuse.Langfuse(secret_key=secret, public_key=public, host=spec.base_url)
        timeout = op_timeout if op_timeout is not None else DEFAULT_OP_TIMEOUT_SECONDS
        return cls(handle, base_url=spec.base_url, auth=basic_auth_header(public, secret), judge=judge, timeout=timeout)

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
        fetched = self._handle.fetch_trace(str(payload["trace_id"]))
        name = getattr(getattr(fetched, "data", fetched), "name", "")
        return OpDraft(artifact_ids=(str(payload["trace_id"]),), response_excerpt=f"name={name}")

    def _op_create_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.create_prompt(
            name=str(payload["name"]), prompt=str(payload.get("text", "v1")), labels=["production"]
        )
        return OpDraft(artifact_ids=(str(payload["name"]),), response_excerpt=f"version={prompt.version}")

    def _op_create_prompt_version(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_create_prompt({**payload, "text": str(payload.get("text", "v2"))})

    def _op_fetch_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.get_prompt(str(payload["name"]))
        return OpDraft(response_excerpt=f"version={prompt.version} prompt={str(prompt.prompt)[:80]}")

    def _op_rollback_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        # Label-move rollback via the public v2 API (no stable SDK surface for it).
        path = f"/api/public/v2/prompts/{payload['name']}/versions/{payload.get('version', 1)}"
        result = self._rest.call(
            "PATCH",
            self._base_url + path,
            headers=self._auth,
            json_body={"newLabels": ["production"]},
            timeout=self._timeout,
        )
        return _draft(result)

    def _op_create_dataset(self, payload: Mapping[str, object]) -> OpDraft:
        self._handle.create_dataset(name=str(payload["name"]))
        return OpDraft(artifact_ids=(str(payload["name"]),))

    def _op_insert_dataset_items(self, payload: Mapping[str, object]) -> OpDraft:
        count = int(str(payload.get("count", 2)))
        for index in range(count):
            self._handle.create_dataset_item(
                dataset_name=str(payload["name"]), input={"q": f"item-{index}"}, expected_output=f"a-{index}"
            )
        return OpDraft(response_excerpt=f"inserted={count}")

    def _op_fetch_dataset(self, payload: Mapping[str, object]) -> OpDraft:
        dataset = self._handle.get_dataset(str(payload["name"]))
        item_ids = tuple(str(item.id) for item in list(dataset.items)[:3])
        return OpDraft(artifact_ids=item_ids, response_excerpt=f"items={len(dataset.items)}")

    def _op_link_dataset_run(self, payload: Mapping[str, object]) -> OpDraft:
        self._handle.api.dataset_run_items.create(
            request={
                "runName": str(payload.get("run_name", "bv-run")),
                "datasetItemId": str(payload["item_id"]),
                "traceId": str(payload["trace_id"]),
            }
        )
        return OpDraft(artifact_ids=(str(payload.get("run_name", "bv-run")),))

    def _op_create_agent_trace(self, payload: Mapping[str, object]) -> OpDraft:
        trace = self._handle.trace(name=str(payload.get("name", "bv-agent")))
        span = trace.span(name="tool:search", metadata={"tool": "search", "kind": "tool"})
        span.end()
        step = trace.span(name="tool:calc", metadata={"tool": "calc", "kind": "tool"})
        step.end()
        self._handle.flush()
        return OpDraft(artifact_ids=(str(trace.id),), response_excerpt="spans=2")

    def _op_score_agent_trace(self, payload: Mapping[str, object]) -> OpDraft:
        self._handle.score(trace_id=str(payload["trace_id"]), name="task_success", value=1.0)
        self._handle.flush()
        return OpDraft(artifact_ids=(str(payload["trace_id"]),))

    def _op_create_experiment_run(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_link_dataset_run(payload)  # a Langfuse "experiment" is a dataset run

    # ---------------------------------------------------------- REST operations
    def _op_otlp_export(self, payload: Mapping[str, object]) -> OpDraft:
        body = payload.get("otlp_body")
        result = self._rest.call(
            "POST",
            self._base_url + _OTLP_PATH,
            headers=self._auth,
            json_body=body if isinstance(body, dict) else {"resourceSpans": []},
            timeout=self._timeout,
        )
        return _draft(result)

    def _op_fetch_otel_trace(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_fetch_trace(payload)

    def _op_fetch_judge_scores(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"/api/public/v2/scores?traceId={payload.get('trace_id', '')}")

    def _op_fetch_agent_scores(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_fetch_judge_scores(payload)

    def _op_configure_judge(self, payload: Mapping[str, object]) -> OpDraft:
        judge_url = self._judge.base_url if self._judge else str(payload.get("judge_url", ""))
        return self._post("/api/public/eval-configs", {"model": {"baseUrl": judge_url}})

    def _op_run_judge_eval(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/evals/run", {"traceId": str(payload.get("trace_id", ""))})

    def _op_run_rag_metric(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/evals/rag", dict(payload))

    def _op_compare_runs(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get(f"/api/public/datasets/{payload['name']}/runs")

    def _op_diff_runs(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_compare_runs(payload)

    def _op_invoke_guardrail(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/guardrails/check", {"input": str(payload.get("text", "probe"))})

    def _op_create_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/alerts", {"name": "bv-alert", "threshold": 1})

    def _op_verify_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get("/api/public/alerts")

    def _op_create_annotation_queue(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/annotation-queues", {"name": str(payload.get("name", "bv-queue"))})

    def _op_submit_annotation_score(self, payload: Mapping[str, object]) -> OpDraft:
        queue = payload.get("queue_id", "bv-queue")
        return self._post(
            f"/api/public/annotation-queues/{queue}/items", {"objectId": str(payload.get("trace_id", ""))}
        )

    def _op_fetch_annotations(self, payload: Mapping[str, object]) -> OpDraft:
        return self._get("/api/public/annotation-queues")

    def _op_invoke_redteam(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post("/api/public/red-teaming/run", {"target": "probe"})

    def _op_probe_endpoint(self, payload: Mapping[str, object]) -> OpDraft:
        result = self._rest.call("GET", str(payload["url"]), timeout=min(self._timeout, 5.0))
        return _draft(result)

    def _ops(self) -> Mapping[str, OpHandler]:
        return {name.removeprefix("_op_"): getattr(self, name) for name in dir(self) if name.startswith("_op_")}
