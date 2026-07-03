"""Unit tests for forge.normalize: deterministic ids, canonical schema, trace, metadata."""

from __future__ import annotations

from forge import normalize


def test_scenario_id_deterministic():
    a = normalize.scenario_id("f.jsonl", "1", "s", "t", "Hello  World")
    b = normalize.scenario_id("f.jsonl", "1", "s", "t", "hello world")  # normalized away
    assert a == b
    assert a.startswith("scn_") and len(a) == len("scn_") + 16


def test_scenario_id_path_separator_normalized():
    unix = normalize.scenario_id("dir/sub/f.jsonl", "1", None, None, "p")
    win = normalize.scenario_id("dir\\sub\\f.jsonl", "1", None, None, "p")
    assert unix == win


def test_scenario_id_varies_with_inputs():
    base = normalize.scenario_id("f", "1", None, None, "p")
    assert base != normalize.scenario_id("f", "2", None, None, "p")
    assert base != normalize.scenario_id("f", "1", None, None, "different")


def test_golden_id_matches_pinned_value():
    # The same value pinned in evals/evals.json (golden-values eval), computed from fixture 1.
    sid = normalize.scenario_id(
        "evals/fixtures/full-dataset/records.jsonl",
        "1",
        "s1",
        "t1",
        "Find the refund policy and tell the user",
    )
    assert sid == "scn_d343445c10e8f235"


def test_to_canonical_missing_fields_are_null_not_omitted():
    c = normalize.to_canonical(("f.jsonl", "1", {"prompt": "hi"}))
    for field in ("session_id", "turn_id", "task_context", "expected_intent", "expected_outcome", "trace"):
        assert field in c and c[field] is None
    assert c["metadata"]["complexity"] == "unclassified"
    assert c["metadata"]["taxonomy_tags"] == []


def test_to_canonical_preserves_source_scenario_id():
    c = normalize.to_canonical(("f", "1", {"prompt": "x", "scenario_id": "custom-id"}))
    assert c["scenario_id"] == "custom-id"


def test_to_canonical_generates_id_when_missing():
    c = normalize.to_canonical(("f", "1", {"prompt": "x"}))
    assert c["scenario_id"].startswith("scn_")


def test_trace_present_with_all_fields_when_execution_data():
    raw = {"prompt": "x", "trace": {"tool_names": ["a"], "retrieved_ids": ["d1"]}}
    c = normalize.to_canonical(("f", "1", raw))
    trace = c["trace"]
    for field in (
        "tool_names",
        "tool_invocation_order",
        "tool_arguments",
        "tool_outputs",
        "retrieved_entities",
        "retrieved_ids",
        "model_name",
        "token_usage",
        "latency_ms",
        "trace_ids",
    ):
        assert field in trace
    # invocation order defaults to tool_names when not given
    assert trace["tool_invocation_order"] == ["a"]


def test_trace_none_in_bootstrap():
    c = normalize.to_canonical(("f", "1", {"prompt": "x", "expected_outcome": {"a": 1}}))
    assert c["trace"] is None


def test_metadata_explicit_complexity_and_tags():
    raw = {"prompt": "x", "complexity": "high", "taxonomy_tags": ["billing"]}
    md = normalize.to_canonical(("f", "1", raw))["metadata"]
    assert md["complexity"] == "high" and md["complexity_source"] == "explicit"
    assert md["taxonomy_tags"] == ["billing"] and md["taxonomy_source"] == "explicit"


def test_metadata_invalid_complexity_falls_back_to_unclassified():
    md = normalize.to_canonical(("f", "1", {"prompt": "x", "complexity": "huge"}))["metadata"]
    assert md["complexity"] == "unclassified" and md["complexity_source"] == "unclassified"


def test_expected_action_types_from_evidence():
    raw = {
        "prompt": "x",
        "trace": {"tool_names": ["t"], "retrieved_ids": ["d"]},
        "response": "r",
        "completion_status": "success",
    }
    types = normalize.to_canonical(("f", "1", raw))["metadata"]["expected_action_types"]
    assert set(types) == {"retrieve", "call_tool", "respond", "complete_workflow"}


def test_expected_action_types_unclassified_when_no_evidence():
    types = normalize.to_canonical(("f", "1", {"prompt": "x"}))["metadata"]["expected_action_types"]
    assert types == ["unclassified"]


def test_evaluator_applicability_response_requires_comparison_target():
    # response present but no comparison target -> response flag False
    raw = {"prompt": "x", "response": "r"}
    flags = normalize.to_canonical(("f", "1", raw))["metadata"]["evaluator_applicability"]
    assert flags["response"] is False
    # add a comparison target -> True
    raw2 = {"prompt": "x", "response": "r", "expected_output_fields": {"a": 1}}
    flags2 = normalize.to_canonical(("f", "1", raw2))["metadata"]["evaluator_applicability"]
    assert flags2["response"] is True
