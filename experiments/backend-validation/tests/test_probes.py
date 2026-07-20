"""Unit tests driving every L1 probe against scripted clients; evidence notes verified."""

from __future__ import annotations

from backend_validation import probes
from backend_validation.clients import NullProbeClient
from backend_validation.observables import Observable, OpOutcome
from backend_validation.probes import parsed_score_in_unit_range, structured
from backend_validation.runner import ProbeContext, run_probe
from backend_validation.settings import JudgeSpec, RetrySpec, TimeoutSpec

probes.load_all()

TIMEOUTS = TimeoutSpec(op_seconds=5, probe_budget_seconds=60)
RETRIES = RetrySpec(max_attempts=1, backoff_base_seconds=0)
JUDGE = JudgeSpec(base_url="http://127.0.0.1:18323/v1", model="m", api_key_env="BV_JUDGE_API_KEY")


def _run(probe_id: str, client: NullProbeClient, marker: str = "m1") -> list[Observable]:
    ctx = ProbeContext(
        backend_id=client.backend_id,
        run_marker=marker,
        judge=JUDGE,
        control_endpoint="http://127.0.0.1:1/",
    )
    return run_probe(probe_id, "cell", client, ctx, TIMEOUTS, RETRIES, sleeper=lambda _s: None)


def _extra(observables: list[Observable], operation: str) -> dict[str, object]:
    for observable in observables:
        if observable.outcome.operation == operation:
            return observable.extra
    raise AssertionError(f"no observable for operation {operation}")


def _ok(operation: str, **fields: object) -> OpOutcome:
    return OpOutcome(operation=operation, status="ok", latency_ms=1.0, **fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------- helpers
def test_structured_heuristic() -> None:
    assert structured('HTTP 200: {"a": 1}')
    assert structured("HTTP 201: [1, 2]")
    assert not structured("HTTP 404: {}")  # non-2xx is never machine-readable evidence
    assert not structured("HTTP 200: plain words")


def test_parsed_score_in_unit_range() -> None:
    assert parsed_score_in_unit_range("metric score=0.83 done")
    assert parsed_score_in_unit_range("score=1.0")
    assert not parsed_score_in_unit_range("score=1.4")
    assert not parsed_score_in_unit_range("score=abc")
    assert not parsed_score_in_unit_range("no score here")


# ---------------------------------------------------------------------- probes
def test_tracing_roundtrip_notes_visibility() -> None:
    client = NullProbeClient(backend_id="langfuse")
    observables = _run("l1.tracing.roundtrip", client)
    assert _extra(observables, "fetch_trace")["trace_visible"] is True
    assert [operation for operation, _payload in client.calls] == ["create_trace", "fetch_trace"]


def test_tracing_visibility_false_when_fetch_fails() -> None:
    client = NullProbeClient(
        backend_id="langfuse",
        script={"fetch_trace": OpOutcome(operation="fetch_trace", status="error", latency_ms=1.0)},
    )
    observables = _run("l1.tracing.roundtrip", client)
    assert _extra(observables, "fetch_trace")["trace_visible"] is False


def test_otlp_probe_builds_body_and_reuses_trace_id() -> None:
    client = NullProbeClient(backend_id="opik")
    _run("l1.otel.raw_otlp_ingest", client)
    export_payload = client.calls[0][1]
    fetch_payload = client.calls[1][1]
    assert "resourceSpans" in str(export_payload["otlp_body"])
    assert export_payload["trace_id"] == fetch_payload["trace_id"]
    assert len(str(export_payload["trace_id"])) == 32  # OTLP hex id, non-vendor construction


def test_prompt_cycle_notes_latest_match() -> None:
    client = NullProbeClient(
        backend_id="langfuse",
        script={"fetch_prompt": _ok("fetch_prompt", response_excerpt="version=2 prompt=v2-m1")},
    )
    observables = _run("l1.prompts.version_cycle", client)
    assert _extra(observables, "fetch_prompt")["fetched_latest_matches"] is True
    operations = [operation for operation, _payload in client.calls]
    assert operations == ["create_prompt", "create_prompt_version", "fetch_prompt", "rollback_prompt"]


def test_dataset_probe_chains_item_and_trace_ids() -> None:
    client = NullProbeClient(
        backend_id="opik",
        script={
            "create_trace": _ok("create_trace", artifact_ids=("trace-7",)),
            "fetch_dataset": _ok("fetch_dataset", artifact_ids=("item-3",), response_excerpt="items=2"),
        },
    )
    observables = _run("l1.datasets.crud_link", client)
    assert _extra(observables, "fetch_dataset")["item_count_matches"] is True
    link_payload = dict(client.calls[-1][1])
    assert link_payload["item_id"] == "item-3" and link_payload["trace_id"] == "trace-7"


def test_judge_probe_notes_configuration_and_persistence() -> None:
    client = NullProbeClient(
        backend_id="langfuse",
        script={"fetch_judge_scores": _ok("fetch_judge_scores", response_excerpt='HTTP 200: {"scores": []}')},
    )
    observables = _run("l1.judge.eval_scores", client)
    assert _extra(observables, "configure_judge")["judge_configurable_to_local"] is True
    assert _extra(observables, "fetch_judge_scores")["score_persisted"] is True
    configure_payload = client.calls[0][1]
    assert configure_payload["judge_url"] == JUDGE.base_url  # pinned local judge wired through


def test_rag_probe_requires_parseable_unit_score() -> None:
    good = NullProbeClient(script={"run_rag_metric": _ok("run_rag_metric", response_excerpt="score=0.9")})
    assert _extra(_run("l1.rag.builtin_metric", good), "run_rag_metric")["score_in_range"] is True
    bad = NullProbeClient(script={"run_rag_metric": _ok("run_rag_metric", response_excerpt="HTTP 200: {}")})
    assert _extra(_run("l1.rag.builtin_metric", bad), "run_rag_metric")["score_in_range"] is False


def test_agent_probe_notes_tool_spans() -> None:
    client = NullProbeClient(
        script={"create_agent_trace": _ok("create_agent_trace", artifact_ids=("t-1",), response_excerpt="spans=2")}
    )
    observables = _run("l1.agent.multistep_scored", client)
    assert _extra(observables, "create_agent_trace")["tool_spans_recorded"] is True
    assert client.calls[-1][0] == "fetch_agent_scores"


def test_ci_compare_derives_nonzero_exit_from_machine_readable() -> None:
    client = NullProbeClient(
        script={"compare_runs": _ok("compare_runs", response_excerpt='HTTP 200: {"runs": [1, 2]}')}
    )
    observables = _run("l1.ci.two_run_compare", client)
    extra = _extra(observables, "compare_runs")
    assert extra["machine_readable"] is True and extra["nonzero_exit_available"] is True
    unstructured = NullProbeClient(script={"compare_runs": _ok("compare_runs", response_excerpt="HTTP 200: nope")})
    extra2 = _extra(_run("l1.ci.two_run_compare", unstructured), "compare_runs")
    assert extra2["machine_readable"] is False and extra2["nonzero_exit_available"] is False


def test_diff_runs_notes_structured_payload() -> None:
    client = NullProbeClient(script={"diff_runs": _ok("diff_runs", response_excerpt='HTTP 200: [{"run": 1}]')})
    assert _extra(_run("l1.compare.diff_runs", client), "diff_runs")["diff_machine_readable"] is True


def test_guardrails_probe_notes_verdict() -> None:
    client = NullProbeClient(
        script={"invoke_guardrail": _ok("invoke_guardrail", response_excerpt='HTTP 200: {"flagged": true}')}
    )
    assert _extra(_run("l1.guardrails.invoke", client), "invoke_guardrail")["guardrail_verdict_returned"] is True


def test_alerting_annotation_and_redteam_sequences() -> None:
    client = NullProbeClient(backend_id="opik")
    _run("l1.alerting.rule_via_api", client)
    assert [operation for operation, _p in client.calls] == ["create_alert_rule", "verify_alert_rule"]
    annotation_client = NullProbeClient(backend_id="opik")
    _run("l1.annotation.queue_api", annotation_client)
    operations = [operation for operation, _p in annotation_client.calls]
    assert operations == ["create_trace", "create_annotation_queue", "submit_annotation_score", "fetch_annotations"]
    redteam_client = NullProbeClient(backend_id="langfuse")
    _run("l1.redteam.invoke", redteam_client)
    assert redteam_client.calls[0][0] == "invoke_redteam"
