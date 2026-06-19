"""Step 6: build ground-truth mappings, stored separately from canonical scenarios (§4).

Only emit fields the source explicitly supports; null/empty otherwise. No inference unless
the source directly provides the value.
"""
from __future__ import annotations

from typing import Any


def to_ground_truth(canonical: dict[str, Any]) -> dict[str, Any]:
    """Build one §4 mapping referencing ``canonical['scenario_id']``."""
    obj = canonical["_raw"]

    expected_entities = obj.get("expected_entities")
    if not isinstance(expected_entities, list):
        # Fall back to retrieved entities only when explicitly marked as ground truth.
        expected_entities = obj.get("ground_truth_entities") if isinstance(obj.get("ground_truth_entities"), list) else []

    expected_tools = obj.get("expected_tools")
    if not isinstance(expected_tools, list):
        expected_tools = []

    expected_sequence = obj.get("expected_tool_sequence")
    if not isinstance(expected_sequence, list):
        expected_sequence = []

    return {
        "scenario_id": canonical["scenario_id"],
        "expected_entities": [e for e in expected_entities],
        "expected_output_fields": obj.get("expected_output_fields") if isinstance(obj.get("expected_output_fields"), dict) else None,
        "expected_tools": [str(t) for t in expected_tools],
        "expected_tool_sequence": [str(t) for t in expected_sequence],
        "expected_workflow_completion_status": obj.get("expected_workflow_completion_status")
        if isinstance(obj.get("expected_workflow_completion_status"), str)
        else (obj.get("completion_status") if isinstance(obj.get("completion_status"), str) else None),
        "expected_final_state": obj.get("expected_final_state") if isinstance(obj.get("expected_final_state"), dict) else None,
        "grading_notes": obj.get("grading_notes") if isinstance(obj.get("grading_notes"), str) else None,
        "provenance": canonical["provenance"],
    }


def build_all(canonicals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [to_ground_truth(c) for c in canonicals]
