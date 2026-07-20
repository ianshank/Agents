"""L1 probes: guardrails, alerting, human-annotation APIs, and the red-teaming control.

Guardrails and red-teaming double as expected-fail negative controls where the matrix
says "absent" (per-backend ``expectation`` in PROBES.yaml drives that; the probe body is
identical either way — honesty lives in the recorded outcome, not in the probe).
"""

from __future__ import annotations

from backend_validation.probes import structured
from backend_validation.registry import register
from backend_validation.runner import ProbeRun


@register("l1.guardrails.invoke")
def guardrails_invoke(run: ProbeRun) -> None:
    checked = run.op("invoke_guardrail", {"text": f"probe {run.ctx.run_marker}: my SSN is 000-00-0000"})
    checked.note(guardrail_verdict_returned=checked.ok and structured(checked.outcome.response_excerpt))


@register("l1.alerting.rule_via_api")
def alerting_rule_via_api(run: ProbeRun) -> None:
    run.op("create_alert_rule", {"name": f"bv-alert-{run.ctx.run_marker}"})
    run.op("verify_alert_rule", {})


@register("l1.annotation.queue_api")
def annotation_queue_api(run: ProbeRun) -> None:
    queue_name = f"bv-queue-{run.ctx.run_marker}"
    trace = run.op("create_trace", {"name": f"bv-anno-{run.ctx.run_marker}"})
    queue = run.op("create_annotation_queue", {"name": queue_name})
    run.op(
        "submit_annotation_score",
        {"queue_id": queue.first_artifact(queue_name), "trace_id": trace.first_artifact()},
    )
    run.op("fetch_annotations", {})


@register("l1.redteam.invoke")
def redteam_invoke(run: ProbeRun) -> None:
    run.op("invoke_redteam", {"target": f"bv-{run.ctx.run_marker}"})
