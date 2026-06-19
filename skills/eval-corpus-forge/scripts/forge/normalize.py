"""Steps 2-5: normalize raw records into canonical scenarios with deterministic IDs.

Missing values are represented as null / empty list / "unclassified" — never omitted (§3).
No fabrication: trace fields and metadata are only populated from what the source provides.
"""
from __future__ import annotations

import hashlib
from typing import Any

from forge.ingest import Record, has_execution_artifact

_PROMPT_KEYS = ("raw_prompt", "prompt", "input", "question", "user_message")
_ACTION_TYPES = ("retrieve", "call_tool", "respond", "complete_workflow")


def _first_str(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _normalize_prompt(text: str) -> str:
    return " ".join(text.split()).lower()


def scenario_id(
    source_file: str,
    locator: str,
    session_id: str | None,
    turn_id: str | None,
    prompt: str,
) -> str:
    """Deterministic id from stable attributes (§3.1). Same input -> same id across runs.

    Backslashes in ``source_file`` are normalized to forward slashes so the same input
    layout yields identical ids on Windows and Unix.
    """
    normalized_file = source_file.replace("\\", "/")
    key = "\x1f".join(
        [normalized_file, str(locator), session_id or "", turn_id or "", _normalize_prompt(prompt)]
    )
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"scn_{digest[:16]}"


def _build_trace(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Build the §3.2 trace block iff the record has execution data. All fields present."""
    if not has_execution_artifact(obj):
        return None
    src = obj.get("trace") if isinstance(obj.get("trace"), dict) else obj
    tool_names = src.get("tool_names")
    if not isinstance(tool_names, list):
        tool_names = []
    order = src.get("tool_invocation_order")
    if not isinstance(order, list):
        # Preserve order from tool_names when an explicit order is absent.
        order = list(tool_names)
    return {
        "tool_names": [str(t) for t in tool_names],
        "tool_invocation_order": [str(t) for t in order],
        "tool_arguments": src.get("tool_arguments") if isinstance(src.get("tool_arguments"), list) else [],
        "tool_outputs": src.get("tool_outputs") if isinstance(src.get("tool_outputs"), list) else [],
        "retrieved_entities": src.get("retrieved_entities") if isinstance(src.get("retrieved_entities"), list) else [],
        "retrieved_ids": [str(i) for i in src.get("retrieved_ids", [])] if isinstance(src.get("retrieved_ids"), list) else [],
        "model_name": src.get("model_name") if isinstance(src.get("model_name"), str) else None,
        "token_usage": src.get("token_usage") if isinstance(src.get("token_usage"), dict) else None,
        "latency_ms": src.get("latency_ms") if isinstance(src.get("latency_ms"), (int, float)) else None,
        "trace_ids": [str(i) for i in src.get("trace_ids", [])] if isinstance(src.get("trace_ids"), list) else [],
    }


def _expected_action_types(obj: dict[str, Any], trace: dict[str, Any] | None) -> list[str]:
    """Infer expected action types from explicit evidence only (no fabrication)."""
    types: list[str] = []
    explicit = obj.get("expected_action_types")
    if isinstance(explicit, list):
        valid = [t for t in explicit if t in _ACTION_TYPES]
        if valid:
            return valid
    if trace:
        if trace["retrieved_ids"] or trace["retrieved_entities"]:
            types.append("retrieve")
        if trace["tool_names"]:
            types.append("call_tool")
    if _first_str(obj, ("response", "model_output")):
        types.append("respond")
    if obj.get("workflow_completion") or obj.get("completion_status"):
        types.append("complete_workflow")
    return types or ["unclassified"]


def _has_comparison_target(obj: dict[str, Any]) -> bool:
    """Response view requires a distinct comparison target (revision 6)."""
    if isinstance(obj.get("expected_output_fields"), dict) and obj["expected_output_fields"]:
        return True
    return bool(isinstance(obj.get("rubric"), str) and obj["rubric"].strip())


def _evaluator_applicability(obj: dict[str, Any], trace: dict[str, Any] | None) -> dict[str, bool]:
    """Per-scenario flags derived from the SAME evidence predicates the views use."""
    retrieval = bool(trace and (trace["retrieved_ids"] or trace["retrieved_entities"]))
    tool = bool(trace and trace["tool_names"])
    response = bool(_first_str(obj, ("response", "model_output")) and _has_comparison_target(obj))
    end_to_end = bool(
        obj.get("expected_outcome")
        or obj.get("expected_final_state")
        or obj.get("completion_status")
        or obj.get("workflow_completion")
    )
    return {
        "retrieval": retrieval,
        "tool_invocation": tool,
        "response": response,
        "end_to_end": end_to_end,
    }


def _metadata(obj: dict[str, Any], trace: dict[str, Any] | None) -> dict[str, Any]:
    """§3.3 metadata. v1 has no silent inference engine: explicit or unclassified only."""
    complexity = obj.get("complexity")
    if complexity in ("low", "medium", "high"):
        complexity_val, complexity_src = complexity, "explicit"
    else:
        complexity_val, complexity_src = "unclassified", "unclassified"

    tags = obj.get("taxonomy_tags")
    if isinstance(tags, list) and tags:
        taxonomy_val, taxonomy_src = [str(t) for t in tags], "explicit"
    else:
        taxonomy_val, taxonomy_src = [], "unclassified"

    return {
        "complexity": complexity_val,
        "complexity_source": complexity_src,
        "taxonomy_tags": taxonomy_val,
        "taxonomy_source": taxonomy_src,
        "expected_action_types": _expected_action_types(obj, trace),
        "evaluator_applicability": _evaluator_applicability(obj, trace),
    }


def to_canonical(record: Record) -> dict[str, Any]:
    """Convert one raw record into the canonical scenario schema (§3)."""
    source_file, locator, obj = record
    prompt = _first_str(obj, _PROMPT_KEYS) or ""
    session_id = obj.get("session_id") if isinstance(obj.get("session_id"), str) else None
    turn_id = obj.get("turn_id") if isinstance(obj.get("turn_id"), str) else None

    sid = obj.get("scenario_id")
    if not isinstance(sid, str) or not sid.strip():
        sid = scenario_id(source_file, locator, session_id, turn_id, prompt)

    trace = _build_trace(obj)
    provenance = {
        "source_file": source_file,
        "locator": locator,
        "session_id": session_id,
        "turn_id": turn_id,
    }
    return {
        "scenario_id": sid,
        "session_id": session_id,
        "turn_id": turn_id,
        "raw_prompt": prompt,
        "task_context": _first_str(obj, ("task_context", "system", "context")),
        "expected_intent": _first_str(obj, ("expected_intent", "intent")),
        "expected_outcome": obj.get("expected_outcome") if isinstance(obj.get("expected_outcome"), dict) else None,
        "provenance": provenance,
        "trace": trace,
        "metadata": _metadata(obj, trace),
        # Carry comparison-target hints forward for ground-truth/views without re-reading source.
        "_raw": obj,
    }


def normalize_all(records: list[Record]) -> list[dict[str, Any]]:
    return [to_canonical(r) for r in records]
