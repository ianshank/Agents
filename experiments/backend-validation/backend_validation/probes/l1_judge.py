"""L1 judge-class probes (k=3): LLM-as-judge plumbing, built-in RAG metric, agent evals.

These test score PLUMBING (configurable to the local judge, persisted, queryable) — never
judge accuracy; the judge model is pinned and identical across backends (spec risk table).
"""

from __future__ import annotations

from backend_validation.probes import parsed_score_in_unit_range
from backend_validation.registry import register
from backend_validation.runner import ProbeRun

_RAG_FIXTURE = {
    "question": "What color is the sky on a clear day?",
    "contexts": ["The sky appears blue on a clear day due to Rayleigh scattering."],
    "answer": "Blue.",
}


def _judge_url(run: ProbeRun) -> str:
    return run.ctx.judge.base_url if run.ctx.judge else ""


@register("l1.judge.eval_scores")
def judge_eval_scores(run: ProbeRun) -> None:
    configured = run.op("configure_judge", {"judge_url": _judge_url(run)})
    configured.note(judge_configurable_to_local=configured.ok)
    trace = run.op("create_trace", {"name": f"bv-judge-{run.ctx.run_marker}"})
    run.op("run_judge_eval", {"trace_id": trace.first_artifact(), "judge_url": _judge_url(run)})
    scores = run.op("fetch_judge_scores", {"trace_id": trace.first_artifact()})
    scores.note(score_persisted=scores.ok and bool(scores.outcome.response_excerpt))


@register("l1.rag.builtin_metric")
def rag_builtin_metric(run: ProbeRun) -> None:
    result = run.op("run_rag_metric", {**_RAG_FIXTURE, "judge_url": _judge_url(run)})
    result.note(score_in_range=result.ok and parsed_score_in_unit_range(result.outcome.response_excerpt))


@register("l1.agent.multistep_scored")
def agent_multistep_scored(run: ProbeRun) -> None:
    trace = run.op("create_agent_trace", {"name": f"bv-agent-{run.ctx.run_marker}"})
    trace.note(tool_spans_recorded=trace.ok and "spans=2" in trace.outcome.response_excerpt)
    run.op("score_agent_trace", {"trace_id": trace.first_artifact()})
    run.op("fetch_agent_scores", {"trace_id": trace.first_artifact()})
