"""L1 probes: tracing round-trip and raw (non-vendor-SDK) OTLP ingest."""

from __future__ import annotations

import hashlib

from backend_validation.registry import register
from backend_validation.runner import ProbeRun


@register("l1.tracing.roundtrip")
def tracing_roundtrip(run: ProbeRun) -> None:
    created = run.op("create_trace", {"name": f"bv-trace-{run.ctx.run_marker}"})
    fetched = run.op("fetch_trace", {"trace_id": created.first_artifact()})
    fetched.note(trace_visible=fetched.ok and bool(fetched.outcome.artifact_ids))


def _otlp_body(trace_hex: str, span_name: str) -> dict[str, object]:
    """Minimal OTLP/JSON export — hand-built precisely so no vendor SDK is involved."""
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "bv-probe"}}]},
                "scopeSpans": [
                    {
                        "scope": {"name": "backend-validation"},
                        "spans": [
                            {
                                "traceId": trace_hex,
                                "spanId": trace_hex[:16],
                                "name": span_name,
                                "kind": 1,
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                            }
                        ],
                    }
                ],
            }
        ]
    }


@register("l1.otel.raw_otlp_ingest")
def raw_otlp_ingest(run: ProbeRun) -> None:
    trace_hex = hashlib.sha256(run.ctx.run_marker.encode("utf-8")).hexdigest()[:32]
    # The run-scoped span name is the recovery needle: some backends (Opik) assign their
    # own ids to OTLP-ingested traces, so fetching by the exported id is a guaranteed
    # miss — the fetch searches by name instead. Langfuse keeps using trace_id.
    span_name = f"bv-otlp-{run.ctx.run_marker}"
    run.op(
        "otlp_export",
        {"otlp_body": _otlp_body(trace_hex, span_name), "trace_id": trace_hex, "span_name": span_name},
    )
    run.op("fetch_otel_trace", {"trace_id": trace_hex, "span_name": span_name})
