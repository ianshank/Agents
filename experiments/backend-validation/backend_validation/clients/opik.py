"""Opik probe client: SDK-first operations with guarded, version-tolerant fallbacks.

The committed stack pins server 1.7.26 while the SDK pin (``opik>=1.7,<2``) resolves to
1.11.x — a skew this client must survive without corrupting evidence. Every SDK surface
beyond the stable core is therefore reached through a ``getattr``-guarded chain that
degrades to an honest ``error`` draft or a REST route verified against the wheel sources,
never to a silent false positive (the prior body faked several: OTLP fetch by an id the
server never assigns, rollback reading a key no probe sends, a GET posing as a run link).
Self-hosted Opik runs without authentication by default, so a missing API key is tolerated
(workspace header only), not an init failure — the opposite of Langfuse, which
hard-requires its key pair.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

from backend_validation.clients import DEFAULT_OP_TIMEOUT_SECONDS
from backend_validation.clients._dispatch import DispatchProbeClient, OpDraft, OpHandler, draft_from_rest
from backend_validation.clients._ids import uuid7
from backend_validation.clients._rest import RestTransport, UrllibRest
from backend_validation.settings import BackendSpec, JudgeSpec

_API = "/api/v1/private"
# Loopback discard sink for alert webhooks: alert delivery must never leave the host.
_ALERT_SINK_URL = "http://127.0.0.1:9/bv-sink"
_JUDGE_RULE_NAME = "bv-judge-rule"
_JUDGE_PROVIDER_NAME = "bv-local-judge"
# The SDK's default project (config.OPIK_PROJECT_DEFAULT_NAME): handle-created traces land
# there, so judge rules armed against it score exactly the traces the probes create.
_DEFAULT_PROJECT = "Default Project"


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
        timeout: float = DEFAULT_OP_TIMEOUT_SECONDS,
        judge_api_key: str = "",
    ) -> None:
        self._handle = handle
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._rest: RestTransport = rest if rest is not None else UrllibRest()
        self._judge = judge
        self._timeout = timeout
        self._judge_api_key = judge_api_key
        # scheme://netloc of the frontend: the guardrails backend is proxied under
        # /guardrails/ on the SAME published port (official nginx guardrails flavor).
        parsed = urlparse(self._base_url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        # Project the online judge rule was armed against; None until configure_judge
        # succeeds, which run_judge_eval requires (an unarmed eval has no trigger).
        self._armed_project: str | None = None

    @classmethod
    def from_spec(
        cls,
        spec: BackendSpec,
        *,
        judge: JudgeSpec | None = None,
        env: Mapping[str, str] | None = None,
        op_timeout: float | None = None,
    ) -> OpikProbeClient:
        import os

        resolved_env = env if env is not None else os.environ
        api_key = resolved_env.get(spec.credential_env.get("api_key", ""), "")
        judge_api_key = resolved_env.get(judge.api_key_env, "") if judge is not None else ""
        import opik

        handle = opik.Opik(host=f"{spec.base_url}/api", api_key=api_key or None, workspace=spec.workspace)
        # Comet-Workspace scopes every raw REST call to the same workspace the SDK uses;
        # Authorization is the RAW key (no Bearer), sent only when a key is configured.
        auth = {"Comet-Workspace": spec.workspace}
        if api_key:
            auth["Authorization"] = api_key
        timeout = op_timeout if op_timeout is not None else DEFAULT_OP_TIMEOUT_SECONDS
        return cls(
            handle,
            base_url=spec.base_url,
            auth=auth,
            judge=judge,
            timeout=timeout,
            judge_api_key=judge_api_key,
        )

    def close(self) -> None:
        flush = getattr(self._handle, "flush", None)
        if callable(flush):
            flush()

    def _get(self, path: str) -> OpDraft:
        return draft_from_rest(self._rest.call("GET", self._base_url + path, headers=self._auth, timeout=self._timeout))

    def _post(self, path: str, body: dict[str, object]) -> OpDraft:
        result = self._rest.call(
            "POST", self._base_url + path, headers=self._auth, json_body=body, timeout=self._timeout
        )
        return draft_from_rest(result)

    def _fern(self) -> Any:
        # 1.11.x exposes the fern OpikApi as a public property; 1.7.x has no such surface,
        # so every chain through here must tolerate None.
        return getattr(self._handle, "rest_client", None)

    def _project_name(self) -> str:
        # 1.11.x exposes the resolved default as a property; 1.7.x does not — both fall
        # back to the SDK's own default-project constant.
        return str(getattr(self._handle, "project_name", "") or _DEFAULT_PROJECT)

    def _judge_url(self) -> str:
        # Server-side evaluators dial from INSIDE the backend container, where the host's
        # loopback judge is unreachable — prefer the container-visible URL when set.
        if self._judge is None:
            return ""
        return self._judge.container_base_url or self._judge.base_url

    # ----------------------------------------------------------- SDK operations
    def _op_create_trace(self, payload: Mapping[str, object]) -> OpDraft:
        trace = self._handle.trace(name=str(payload.get("name", "bv-probe")))
        self._handle.flush()
        return OpDraft(artifact_ids=(str(trace.id),))

    def _op_fetch_trace(self, payload: Mapping[str, object]) -> OpDraft:
        # get_trace_content raises ApiError(status_code=404) on a missing id; the
        # dispatch base converts that into an honest (retryable) error observable.
        content = self._handle.get_trace_content(id=str(payload["trace_id"]))
        return OpDraft(artifact_ids=(str(payload["trace_id"]),), response_excerpt=f"name={content.name}")

    def _op_fetch_otel_trace(self, payload: Mapping[str, object]) -> OpDraft:
        # Opik assigns its own ids to OTLP-ingested traces, so fetching by the exported
        # 32-hex OTLP id is a guaranteed miss — the only honest recovery is name search.
        needle = str(payload.get("span_name", "") or payload.get("trace_id", ""))
        return self._search_by_name(needle)

    def _search_by_name(self, span_name: str) -> OpDraft:
        search = getattr(self._handle, "search_traces", None)
        if not callable(search):
            return OpDraft(
                status="error",
                response_excerpt=f"search unavailable for name={span_name}",
                stderr="sdk has no search_traces; OTLP ingest cannot be verified",
            )
        traces = list(search(filter_string=f'name contains "{span_name}"'))
        if not traces:  # zero matches returns [], no raise — retryable ingest lag
            return OpDraft(
                status="error",
                response_excerpt=f"matches=0 name={span_name}",
                stderr="trace not searchable yet (retryable)",
            )
        return OpDraft(
            artifact_ids=tuple(str(trace.id) for trace in traces[:3]),
            response_excerpt=f"matches={len(traces)} name={span_name}",
        )

    def _op_create_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.create_prompt(name=str(payload["name"]), prompt=str(payload.get("text", "v1")))
        return OpDraft(artifact_ids=(str(payload["name"]),), response_excerpt=f"commit={prompt.commit}")

    def _op_create_prompt_version(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_create_prompt({**payload, "text": str(payload.get("text", "v2"))})

    def _op_fetch_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        prompt = self._handle.get_prompt(name=str(payload["name"]))
        if prompt is None:  # the SDK returns None on 404, it does not raise
            return OpDraft(
                status="error",
                response_excerpt=f"prompt not found name={payload['name']}",
                stderr="get_prompt returned None (retryable)",
            )
        return OpDraft(response_excerpt=f"commit={prompt.commit} prompt={str(prompt.prompt)[:80]}")

    def _op_rollback_prompt(self, payload: Mapping[str, object]) -> OpDraft:
        text = str(payload.get("text", ""))
        if not text:
            return OpDraft(
                status="error",
                response_excerpt="rollback needs the target version's text",
                stderr="payload carries no 'text'; recreate-as-latest rollback would be unverifiable",
            )
        name = str(payload["name"])
        # create_prompt dedups only against the LATEST version, so recreating an older
        # version's text promotes it to latest — rollback-by-recreate, then verify.
        self._handle.create_prompt(name=name, prompt=text)
        prompt = self._handle.get_prompt(name=name)
        if prompt is None or str(prompt.prompt) != text:
            return OpDraft(
                status="error",
                response_excerpt=f"rollback unverified name={name}",
                stderr="latest prompt text does not match the requested rollback text",
            )
        return OpDraft(artifact_ids=(name,), response_excerpt=f"rolled-back-latest commit={prompt.commit}")

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

    def _op_link_dataset_run(self, payload: Mapping[str, object]) -> OpDraft:
        run_name = str(payload.get("run_name", "bv-run"))
        experiment = self._handle.create_experiment(dataset_name=str(payload.get("name", "")), name=run_name)
        item_id = str(payload.get("item_id", ""))
        trace_id = str(payload.get("trace_id", ""))
        linked = bool(item_id and trace_id) and self._insert_experiment_item(experiment, item_id, trace_id)
        self._handle.flush()  # experiment items are delivered async; flush before reporting
        return OpDraft(
            artifact_ids=(str(getattr(experiment, "id", run_name)),),
            response_excerpt=f"experiment={run_name} item_linked={linked}",
        )

    def _insert_experiment_item(self, experiment: Any, item_id: str, trace_id: str) -> bool:
        insert = getattr(experiment, "insert", None)
        if not callable(insert):
            return False  # pre-insert SDK Experiment: creation alone is the evidence
        try:
            import opik

            references_cls: Any = opik.ExperimentItemReferences
        except (ImportError, AttributeError):
            references_cls = None
        if references_cls is None:  # SDK-less environments: same wire shape as the class
            insert(experiment_items_references=[{"dataset_item_id": item_id, "trace_id": trace_id}])
        else:
            insert(experiment_items_references=[references_cls(dataset_item_id=item_id, trace_id=trace_id)])
        return True

    def _op_create_experiment_run(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_link_dataset_run(payload)  # an Opik "run" is an experiment on a dataset

    def _op_compare_runs(self, payload: Mapping[str, object]) -> OpDraft:
        # get_dataset raises on a missing dataset (dispatch -> honest error); experiments
        # are then listed by dataset ID — the query key is camelCase on the wire.
        dataset = self._handle.get_dataset(str(payload.get("name", "")))
        return self._get(f"{_API}/experiments?datasetId={dataset.id}&size=10")

    def _op_diff_runs(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_compare_runs(payload)

    def _op_fetch_judge_scores(self, payload: Mapping[str, object]) -> OpDraft:
        trace_id = str(payload.get("trace_id", ""))
        content = self._handle.get_trace_content(id=trace_id)
        scores = list(getattr(content, "feedback_scores", None) or [])
        if not scores:  # online rules score asynchronously — empty is retryable, not ok
            return OpDraft(
                status="error",
                response_excerpt=f"scores=0 trace={trace_id}",
                stderr="no feedback scores persisted yet (retryable)",
            )
        return OpDraft(artifact_ids=(trace_id,), response_excerpt=f"scores={len(scores)} trace={trace_id}")

    def _op_fetch_agent_scores(self, payload: Mapping[str, object]) -> OpDraft:
        return self._op_fetch_judge_scores(payload)

    def _op_configure_judge(self, payload: Mapping[str, object]) -> OpDraft:
        judge_url = self._judge_url() or str(payload.get("judge_url", ""))
        fern = self._fern()
        projects = getattr(fern, "projects", None)
        provider_keys = getattr(fern, "llm_provider_key", None)
        evaluators = getattr(fern, "automation_rule_evaluators", None)
        if projects is None or provider_keys is None or evaluators is None:
            # Pre-fern-surface SDKs (1.7.x): honest REST attempt against the verified route.
            return self._post(f"{_API}/automations/evaluators", {"model": {"baseUrl": judge_url}})
        project_name = self._project_name()
        project = projects.retrieve_project(name=project_name)  # the SDK's own name->id resolver
        key_kwargs: dict[str, Any] = {
            "provider": "custom-llm",
            "provider_name": _JUDGE_PROVIDER_NAME,
            "base_url": judge_url,
        }
        if self._judge_api_key:
            key_kwargs["api_key"] = self._judge_api_key
        provider_keys.store_llm_provider_api_key(**key_kwargs)
        evaluators.create_automation_rule_evaluator(request=self._judge_rule(str(project.id)))
        self._armed_project = project_name
        return OpDraft(
            artifact_ids=(_JUDGE_RULE_NAME,),
            response_excerpt=(
                f"evaluator={_JUDGE_RULE_NAME} sampling=1.0 provider={_JUDGE_PROVIDER_NAME} "
                f"base_url={judge_url} project={project_name}"
            ),
        )

    def _judge_rule(self, project_id: str) -> dict[str, Any]:
        """Minimal llm_as_judge rule body (wire keys per the fern AutomationRuleEvaluatorWrite)."""
        model_name = self._judge.model if self._judge is not None else _JUDGE_PROVIDER_NAME
        return {
            "type": "llm_as_judge",
            "action": "evaluator",
            "name": _JUDGE_RULE_NAME,
            "project_id": project_id,
            "sampling_rate": 1.0,
            "code": {
                "model": {"name": model_name, "temperature": 0.0},
                "messages": [
                    {
                        "role": "USER",
                        "content": "Given INPUT {{input}} and OUTPUT {{output}}: is the output a plausible response? Answer task_ok.",
                    }
                ],
                "variables": {"input": "input", "output": "output"},
                "schema": [
                    {"name": "task_ok", "type": "BOOLEAN", "description": "Output plausibly addresses the input."}
                ],
            },
        }

    def _op_run_judge_eval(self, payload: Mapping[str, object]) -> OpDraft:
        if self._armed_project is None:
            return OpDraft(
                status="error",
                response_excerpt="no armed judge rule",
                stderr="configure_judge did not arm an online rule; a server-side eval has no trigger",
            )
        # Online rules score traces AS THEY ARRIVE — re-sending the probe's OWN trace id
        # with scoreable input/output is the platform's real trigger, not a bespoke run
        # endpoint. Same id on purpose: the probe's fetch_judge_scores polls exactly this
        # trace, and the armed rule's {{input}}/{{output}} variables need real fields to
        # map onto (an empty trace gives the evaluator nothing to score).
        trace_id = str(payload.get("trace_id", "")) or None
        trace = self._handle.trace(
            id=trace_id,
            name=f"bv-judge-eval-{trace_id or 'trace'}",
            project_name=self._armed_project,
            input={"input": "What color is the clear daytime sky?"},
            output={"output": "The clear daytime sky is blue."},
        )
        self._handle.flush()
        return OpDraft(
            artifact_ids=(str(trace.id),),
            response_excerpt=f"trace={trace.id} project={self._armed_project} rule={_JUDGE_RULE_NAME}",
        )

    def _op_run_rag_metric(self, payload: Mapping[str, object]) -> OpDraft:
        judge = self._judge
        if judge is None:
            return OpDraft(
                status="error",
                response_excerpt="no judge configured",
                stderr="run_rag_metric needs settings.judge (a pinned local model)",
            )
        metric = self._answer_relevance_metric(judge)
        if metric is None:
            return OpDraft(
                status="error",
                response_excerpt="metrics surface unavailable",
                stderr="opik.evaluation metrics/models not importable in this SDK",
            )
        contexts = payload.get("contexts")
        result = metric.score(
            input=str(payload.get("question", "")),
            output=str(payload.get("answer", "")),
            context=[str(context) for context in contexts] if isinstance(contexts, list) else [],
        )
        if getattr(result, "scoring_failed", False):
            return OpDraft(
                status="error",
                response_excerpt="scoring_failed",
                stderr="metric returned scoring_failed=True (judge unreachable or unparsable output)",
            )
        return OpDraft(response_excerpt=f"metric=answer_relevance score={float(result.value):.2f}")

    def _answer_relevance_metric(self, judge: JudgeSpec) -> Any:
        try:
            from opik.evaluation import metrics, models
        except ImportError:
            return None
        metric_cls = getattr(metrics, "AnswerRelevance", None)
        model_cls = getattr(models, "LiteLLMChatModel", None)
        if metric_cls is None or model_cls is None:
            return None
        # base_url/api_key ride litellm's completion kwargs; the SDK-side metric dials the
        # HOST-visible judge URL (container_base_url is only for server-side evaluators).
        model = model_cls(
            model_name=f"openai/{judge.model}",
            base_url=judge.base_url,
            api_key=self._judge_api_key or "unused",
        )
        # track=False keeps the metric's own LLM traffic out of the traces under test
        # (present in both 1.7.x and 1.11.x AnswerRelevance).
        return metric_cls(model=model, track=False)

    # ---------------------------------------------------------- REST operations
    def _op_otlp_export(self, payload: Mapping[str, object]) -> OpDraft:
        body = payload.get("otlp_body")
        result = self._rest.call(
            "POST",
            f"{self._base_url}{_API}/otel/v1/traces",
            headers=self._auth,  # carries Comet-Workspace so ingest lands in-scope
            json_body=body if isinstance(body, dict) else {"resourceSpans": []},
            timeout=self._timeout,
        )
        return draft_from_rest(result)

    def _op_invoke_guardrail(self, payload: Mapping[str, object]) -> OpDraft:
        text = str(payload.get("text", "probe"))
        # Validation entry mirrors opik.guardrails.guards.PII.get_validation_configs.
        validations: list[dict[str, Any]] = [
            {"type": "PII", "config": {"entities": ["US_SSN", "PHONE_NUMBER"], "language": "en", "threshold": 0.5}}
        ]
        draft = self._guardrails_via_sdk(text, validations)
        if draft is not None:
            return draft
        # Module absent: raw REST to the same URL the SDK client would build
        # ({origin}/guardrails/ prefix is proxied by the frontend's guardrails flavor).
        result = self._rest.call(
            "POST",
            f"{self._origin}/guardrails/api/v1/guardrails/validations",
            headers=self._auth,
            json_body={"text": text, "validations": validations},
            timeout=self._timeout,
        )
        return draft_from_rest(result)

    def _guardrails_via_sdk(self, text: str, validations: list[dict[str, Any]]) -> OpDraft | None:
        try:
            from opik.guardrails import rest_api_client as guardrails_rest
        except ImportError:
            return None
        client_cls = getattr(guardrails_rest, "GuardrailsApiClient", None)
        if client_cls is None:
            return None
        try:
            httpx_module: Any = importlib.import_module("httpx")  # ships with the opik extra
        except ImportError:
            return None
        # Context-managed so every probe invocation closes its connection pool (k=3
        # repetitions plus retries would otherwise leak sockets until GC).
        with httpx_module.Client(timeout=self._timeout) as httpx_client:
            api = client_cls(
                httpx_client=httpx_client,
                # Mirror config.guardrails_backend_host: scheme://netloc + "guardrails/".
                host_url=f"{self._origin}/guardrails/",
            )
            try:
                response = api.validate(text, validations=validations)
            except Exception as exc:
                code = getattr(exc, "status_code", None)
                if code is None:
                    raise  # not an API error; dispatch records it honestly
                body_excerpt = json.dumps(getattr(exc, "body", None))[:160]
                return OpDraft(
                    status="error",
                    response_excerpt=f"HTTP {code}: {body_excerpt}"[:220],
                    stderr=f"http_status={code}",
                )
        verdict = {"validation_passed": bool(getattr(response, "validation_passed", False))}
        # The SDK client returns only on 200, so the structured-evidence prefix is truthful.
        return OpDraft(response_excerpt=f"HTTP 200: {json.dumps(verdict)[:200]}")

    def _op_create_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        name = str(payload.get("name", "bv-alert"))
        alerts = getattr(self._fern(), "alerts", None)
        create = getattr(alerts, "create_alert", None)
        if callable(create):
            create(webhook=self._webhook(_ALERT_SINK_URL), name=name)
            return OpDraft(artifact_ids=(name,), response_excerpt=f"alert={name} webhook={_ALERT_SINK_URL}")
        # A 1.7.26-era SERVER predates the alerts API and may 404 this — honest either way.
        return self._post(f"{_API}/alerts", {"name": name, "webhook": {"url": _ALERT_SINK_URL}})

    def _webhook(self, url: str) -> Any:
        try:
            from opik.rest_api.types import WebhookWrite
        except ImportError:
            return {"url": url}  # fern accepts the equivalent mapping
        return WebhookWrite(url=url)

    def _op_verify_alert_rule(self, payload: Mapping[str, object]) -> OpDraft:
        alerts = getattr(self._fern(), "alerts", None)
        finder = getattr(alerts, "find_alerts", None)
        if callable(finder):
            content = list(getattr(finder(), "content", None) or [])
            if not content:
                return OpDraft(status="error", response_excerpt="alerts=0", stderr="no alerts visible yet (retryable)")
            return OpDraft(response_excerpt=f"alerts={len(content)}")
        return self._get(f"{_API}/alerts")

    def _op_create_annotation_queue(self, payload: Mapping[str, object]) -> OpDraft:
        name = str(payload.get("name", "bv-queue"))
        create_high = getattr(self._handle, "create_traces_annotation_queue", None)
        if callable(create_high):  # 1.11.x high-level surface resolves the project itself
            queue = create_high(name=name)
            return OpDraft(artifact_ids=(str(getattr(queue, "id", name)),), response_excerpt=f"queue={name}")
        fern = self._fern()
        queues = getattr(fern, "annotation_queues", None)
        projects = getattr(fern, "projects", None)
        if queues is not None and projects is not None:
            project = projects.retrieve_project(name=self._project_name())
            queue_id = str(uuid7())  # fern create returns 201/None; the id must be client-minted
            queues.create_annotation_queue(project_id=str(project.id), name=name, scope="trace", id=queue_id)
            return OpDraft(artifact_ids=(queue_id,), response_excerpt=f"queue={name} id={queue_id}")
        queue_id = str(uuid7())
        draft = self._post(f"{_API}/annotation-queues", {"id": queue_id, "name": name, "scope": "trace"})
        if draft.status == "ok":
            return replace(draft, artifact_ids=(queue_id,))
        return draft

    def _op_submit_annotation_score(self, payload: Mapping[str, object]) -> OpDraft:
        queue_id = str(payload.get("queue_id", "bv-queue"))
        trace_id = str(payload.get("trace_id", ""))
        queues = getattr(self._fern(), "annotation_queues", None)
        add = getattr(queues, "add_items_to_annotation_queue", None)
        if callable(add):
            add(id=queue_id, ids=[trace_id])
            return OpDraft(artifact_ids=(queue_id,), response_excerpt=f"queued={trace_id}")
        return self._post(f"{_API}/annotation-queues/{queue_id}/items/add", {"ids": [trace_id]})

    def _op_fetch_annotations(self, payload: Mapping[str, object]) -> OpDraft:
        lister = getattr(self._handle, "get_traces_annotation_queues", None)
        if callable(lister):
            queues = list(lister())
            if not queues:
                return OpDraft(status="error", response_excerpt="queues=0", stderr="no queues visible yet (retryable)")
            return OpDraft(response_excerpt=f"queues={len(queues)}")
        finder = getattr(getattr(self._fern(), "annotation_queues", None), "find_annotation_queues", None)
        if callable(finder):
            content = list(getattr(finder(), "content", None) or [])
            if not content:
                return OpDraft(status="error", response_excerpt="queues=0", stderr="no queues visible yet (retryable)")
            return OpDraft(response_excerpt=f"queues={len(content)}")
        return self._get(f"{_API}/annotation-queues")

    def _op_invoke_redteam(self, payload: Mapping[str, object]) -> OpDraft:
        return self._post(f"{_API}/redteam/run", {"target": "probe"})

    def _op_probe_endpoint(self, payload: Mapping[str, object]) -> OpDraft:
        result = self._rest.call("GET", str(payload["url"]), timeout=min(self._timeout, 5.0))
        return draft_from_rest(result)

    def _ops(self) -> Mapping[str, OpHandler]:
        return {name.removeprefix("_op_"): getattr(self, name) for name in dir(self) if name.startswith("_op_")}
