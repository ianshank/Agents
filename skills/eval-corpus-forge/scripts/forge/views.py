"""Step 7: build the four derived eval views with applicability gating.

A scenario contributes a record to a view ONLY if it carries that view's required evidence.
View records reference scenario_id and a thin projection — never the full canonical record.
If zero records qualify, the view file is empty and the manifest records the reason.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

VIEW_NAMES = ("retrieval_eval", "tool_invocation_eval", "response_eval", "end_to_end_eval")


def _has_comparison_target(raw: dict[str, Any]) -> bool:
    if isinstance(raw.get("expected_output_fields"), dict) and raw["expected_output_fields"]:
        return True
    return bool(isinstance(raw.get("rubric"), str) and raw["rubric"].strip())


def _retrieval_record(c: dict[str, Any]) -> dict[str, Any] | None:
    trace = c.get("trace") or {}
    if not (trace.get("retrieved_ids") or trace.get("retrieved_entities")):
        return None
    return {
        "scenario_id": c["scenario_id"],
        "retrieved_ids": trace.get("retrieved_ids", []),
        "retrieved_entities": trace.get("retrieved_entities", []),
    }


def _tool_record(c: dict[str, Any]) -> dict[str, Any] | None:
    trace = c.get("trace") or {}
    if not trace.get("tool_names"):
        return None
    return {
        "scenario_id": c["scenario_id"],
        "tool_names": trace.get("tool_names", []),
        "tool_invocation_order": trace.get("tool_invocation_order", []),
    }


def _response_record(c: dict[str, Any]) -> dict[str, Any] | None:
    raw = c["_raw"]
    # Prefer a non-blank response, falling back to model_output — consistent with the
    # applicability predicate in normalize._evaluator_applicability.
    response = None
    for key in ("response", "model_output"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            response = val
            break
    if response is None:
        return None
    if not _has_comparison_target(raw):
        return None
    return {
        "scenario_id": c["scenario_id"],
        "response": response,
        "comparison_target": raw.get("expected_output_fields") or {"rubric": raw.get("rubric")},
    }


def _end_to_end_record(c: dict[str, Any]) -> dict[str, Any] | None:
    raw = c["_raw"]
    success_target = (
        c.get("expected_outcome")
        or raw.get("expected_final_state")
        or raw.get("completion_status")
        or raw.get("workflow_completion")
    )
    if not success_target:
        return None
    return {
        "scenario_id": c["scenario_id"],
        "success_target": success_target,
    }


_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] = {
    "retrieval_eval": _retrieval_record,
    "tool_invocation_eval": _tool_record,
    "response_eval": _response_record,
    "end_to_end_eval": _end_to_end_record,
}

_NA_REASONS = {
    "retrieval_eval": "no scenarios contain retrieval data (retrieved ids/entities)",
    "tool_invocation_eval": "no scenarios contain tool-call data",
    "response_eval": "no scenarios contain both a response artifact and a comparison target",
    "end_to_end_eval": "no scenarios contain a success target or expected final state",
}


def build_views(canonicals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return {view_name: {"records": [...], "applicable": bool, "reason": str|None}}."""
    out: dict[str, dict[str, Any]] = {}
    for name, builder in _BUILDERS.items():
        records = [r for r in (builder(c) for c in canonicals) if r is not None]
        applicable = len(records) > 0
        out[name] = {
            "records": records,
            "applicable": applicable,
            "reason": None if applicable else _NA_REASONS[name],
        }
    return out
