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


def _otlp_body(trace_hex: str) -> dict[str, object]:
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
                                "name": "bv-otlp-span",
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
    run.op("otlp_export", {"otlp_body": _otlp_body(trace_hex), "trace_id": trace_hex})
    run.op("fetch_otel_trace", {"trace_id": trace_hex})
