"""Unit tests for forge.views and forge.ground_truth: gating, separation, thin projections."""
from __future__ import annotations

from forge import ground_truth, normalize, views
from forge.package_validate import REQUIRED_SCENARIO_FIELDS

FULL_RAW = {
    "prompt": "do it",
    "expected_outcome": {"ok": True},
    "expected_output_fields": {"ok": True},
    "response": "done",
    "trace": {
        "tool_names": ["a", "b"],
        "tool_invocation_order": ["a", "b"],
        "retrieved_ids": ["d1"],
    },
    "expected_tools": ["a", "b"],
    "expected_tool_sequence": ["a", "b"],
    "completion_status": "success",
}


def _canon(raw):
    return normalize.to_canonical(("f", "1", raw))


def test_full_record_populates_all_views():
    out = views.build_views([_canon(FULL_RAW)])
    for name in views.VIEW_NAMES:
        assert out[name]["applicable"] is True
        assert len(out[name]["records"]) == 1
        assert out[name]["reason"] is None


def test_bootstrap_views_empty_with_reasons():
    out = views.build_views([_canon({"prompt": "x", "expected_outcome": {"a": 1}})])
    # only end_to_end qualifies from expected_outcome
    assert out["end_to_end_eval"]["applicable"] is True
    for name in ("retrieval_eval", "tool_invocation_eval", "response_eval"):
        assert out[name]["applicable"] is False
        assert out[name]["records"] == []
        assert out[name]["reason"]


def test_response_view_requires_comparison_target():
    # response but only expected_outcome (not a comparison target) -> response view empty
    out = views.build_views([_canon({"prompt": "x", "response": "r", "expected_outcome": {"a": 1}})])
    assert out["response_eval"]["applicable"] is False


def test_response_view_falls_back_to_model_output_when_response_blank():
    # whitespace response must fall back to model_output, consistent with applicability
    c = _canon({"prompt": "x", "response": "   ", "model_output": "answer", "expected_output_fields": {"ok": True}})
    assert c["metadata"]["evaluator_applicability"]["response"] is True
    out = views.build_views([c])
    assert out["response_eval"]["applicable"] is True
    assert out["response_eval"]["records"][0]["response"] == "answer"


def test_view_records_are_thin_projections():
    out = views.build_views([_canon(FULL_RAW)])
    for name in views.VIEW_NAMES:
        row = out[name]["records"][0]
        assert "scenario_id" in row
        # a view row must not carry the full canonical schema
        assert not set(row.keys()) >= set(REQUIRED_SCENARIO_FIELDS)


def test_tool_view_preserves_invocation_order():
    out = views.build_views([_canon(FULL_RAW)])
    assert out["tool_invocation_eval"]["records"][0]["tool_invocation_order"] == ["a", "b"]


def test_ground_truth_references_scenario_and_excludes_prompt():
    c = _canon(FULL_RAW)
    gt = ground_truth.to_ground_truth(c)
    assert gt["scenario_id"] == c["scenario_id"]
    assert "raw_prompt" not in gt
    assert gt["expected_tools"] == ["a", "b"]
    assert gt["expected_tool_sequence"] == ["a", "b"]
    assert gt["expected_workflow_completion_status"] == "success"


def test_ground_truth_absent_fields_are_null_or_empty():
    gt = ground_truth.to_ground_truth(_canon({"prompt": "x", "expected_outcome": {"a": 1}}))
    assert gt["expected_tools"] == []
    assert gt["expected_entities"] == []
    assert gt["expected_output_fields"] is None
    assert gt["expected_final_state"] is None
