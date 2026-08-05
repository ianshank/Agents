"""Contract, normalization and serialization guarantees for agent trajectories.

The backwards-compatibility assertions here are the ones ADR 0031 commits to: an
appended field, no reordering, no freezing, and result JSON that is byte-identical
when no trajectory is present.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from eval_harness.core._trajectory import (
    NormalizationConfig,
    canonical_call,
    canonical_calls,
    is_subsequence,
    normalize_arguments,
    normalize_name,
)
from eval_harness.core.types import (
    TRAJECTORY_SCHEMA_VERSION,
    AgentTrajectory,
    EvalItem,
    ItemResult,
    RunResult,
    ScoreResult,
    TargetOutput,
    ToolCallRecord,
    TrajectoryStep,
    trajectory_to_dict,
)
from tests._trajectory_helpers import call, final, observation, run_result, tool_call, tool_error

# --- ADR 0031 compatibility obligations -------------------------------------------


def test_historical_positional_construction_still_works():
    """Obligation 1: the field is appended, so old positional calls keep working."""
    out = TargetOutput("text", 12.5, "boom", {"k": "v"})
    assert (out.output, out.latency_ms, out.error, out.metadata) == ("text", 12.5, "boom", {"k": "v"})
    assert out.trajectory is None


def test_target_output_is_still_mutable():
    """Obligation 2: freezing TargetOutput would break every existing mutation site."""
    out = TargetOutput(output="a")
    out.output = "b"
    out.trajectory = AgentTrajectory(steps=(final("done"),))
    assert out.output == "b"
    assert out.trajectory is not None


def test_trajectory_free_run_serializes_without_the_key():
    """Obligation 4: historical result JSON is byte-identical."""
    payload = run_result(TargetOutput(output="plain")).to_dict()
    assert "trajectory" not in payload["items"][0]
    assert set(payload["items"][0]) == {"id", "inputs", "expected", "output", "error", "latency_ms", "scores"}


def test_trajectory_is_emitted_when_present():
    trajectory = AgentTrajectory(steps=(tool_call("search", {"q": "x"}), observation("hit"), final("done")))
    payload = run_result(TargetOutput(output="ok", trajectory=trajectory)).to_dict()
    emitted = payload["items"][0]["trajectory"]
    assert emitted["schema_version"] == TRAJECTORY_SCHEMA_VERSION
    assert [s["kind"] for s in emitted["steps"]] == ["tool_call", "tool_observation", "final"]
    assert emitted["steps"][0]["tool_call"] == {"name": "search", "arguments": {"q": "x"}}
    # Round-trips through json without a custom encoder.
    assert json.loads(json.dumps(payload, default=str))["items"][0]["trajectory"] == emitted


def test_serialization_omits_empty_optional_keys():
    rendered = trajectory_to_dict(AgentTrajectory(steps=(TrajectoryStep(kind="model_decision"),)))
    assert rendered["steps"] == [{"kind": "model_decision"}]


def test_serialization_includes_populated_optional_keys():
    step = TrajectoryStep(
        kind="tool_call",
        timestamp_ms=99,
        tool_call=ToolCallRecord("t", {"a": 1}, call_id="c1"),
        content="body",
        metadata={"m": 1},
    )
    rendered = trajectory_to_dict(AgentTrajectory(steps=(step,)))["steps"][0]
    assert rendered["timestamp_ms"] == 99
    assert rendered["tool_call"]["call_id"] == "c1"
    assert rendered["content"] == "body"
    assert rendered["metadata"] == {"m": 1}


def test_value_objects_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ToolCallRecord("t").name = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        AgentTrajectory().steps = ()  # type: ignore[misc]


def test_trajectory_schema_version_is_independent_of_config_schema_version():
    from eval_harness.version import SCHEMA_VERSION

    assert TRAJECTORY_SCHEMA_VERSION is not SCHEMA_VERSION


# --- tool_calls() -----------------------------------------------------------------


def test_tool_calls_returns_calls_in_order_ignoring_other_steps():
    trajectory = AgentTrajectory(
        steps=(tool_call("a"), observation("x"), tool_call("b"), final("done")),
    )
    assert [c.name for c in trajectory.tool_calls()] == ["a", "b"]


def test_tool_calls_preserves_duplicates():
    """Duplicates are the precision and loop signal; collapsing them destroys it."""
    trajectory = AgentTrajectory(steps=(tool_call("a"), tool_call("a"), tool_call("a")))
    assert len(trajectory.tool_calls()) == 3


def test_empty_trajectory_has_no_calls():
    assert AgentTrajectory().tool_calls() == ()


# --- normalization ----------------------------------------------------------------


def test_names_are_case_insensitive_and_stripped_by_default():
    cfg = NormalizationConfig()
    assert normalize_name("  Search ", cfg) == "search"


def test_name_normalization_is_configurable():
    assert normalize_name(" Search ", NormalizationConfig(case_sensitive_names=True)) == "Search"
    assert normalize_name(" Search ", NormalizationConfig(strip_names=False)) == " search "


def test_argument_key_order_is_not_significant():
    cfg = NormalizationConfig()
    assert canonical_call(call("t", {"a": 1, "b": 2}), cfg) == canonical_call(call("t", {"b": 2, "a": 1}), cfg)


def test_nested_argument_key_order_is_not_significant():
    cfg = NormalizationConfig()
    left = call("t", {"outer": {"a": 1, "b": [{"y": 2, "x": 1}]}})
    right = call("t", {"outer": {"b": [{"x": 1, "y": 2}], "a": 1}})
    assert canonical_call(left, cfg) == canonical_call(right, cfg)


def test_sequence_order_is_significant():
    cfg = NormalizationConfig()
    assert canonical_call(call("t", {"xs": [1, 2]}), cfg) != canonical_call(call("t", {"xs": [2, 1]}), cfg)


def test_ignored_fields_are_dropped_at_any_depth():
    cfg = NormalizationConfig(ignore_fields=frozenset({"req_id"}))
    left = call("t", {"q": "x", "req_id": "1", "nested": {"req_id": "a", "keep": 1}})
    right = call("t", {"q": "x", "req_id": "2", "nested": {"req_id": "b", "keep": 1}})
    assert canonical_call(left, cfg) == canonical_call(right, cfg)


def test_call_id_never_affects_identity():
    cfg = NormalizationConfig()
    assert canonical_call(ToolCallRecord("t", {}, "c1"), cfg) == canonical_call(ToolCallRecord("t", {}, "c2"), cfg)


def test_compare_arguments_false_matches_on_name_alone():
    cfg = NormalizationConfig(compare_arguments=False)
    assert canonical_call(call("t", {"a": 1}), cfg) == canonical_call(call("t", {"b": 2}), cfg)


def test_strings_are_scalars_not_sequences():
    assert normalize_arguments("abc", NormalizationConfig()) == "abc"


def test_none_and_scalars_pass_through():
    cfg = NormalizationConfig()
    assert normalize_arguments(None, cfg) is None
    assert normalize_arguments(7, cfg) == 7


def test_non_json_native_values_do_not_raise():
    cfg = NormalizationConfig()
    assert canonical_call(call("t", {"when": object()}), cfg)[0] == "t"


def test_canonical_calls_preserves_order_and_duplicates():
    cfg = NormalizationConfig()
    canonical = canonical_calls([call("b"), call("a"), call("a")], cfg)
    assert [name for name, _ in canonical] == ["b", "a", "a"]


# --- is_subsequence ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("reference", "candidate", "expected"),
    [
        (["A", "B"], ["A", "X", "B"], True),
        (["B", "A"], ["A", "X", "B"], False),
        ([], ["A"], True),
        (["A"], [], False),
        (["A", "A"], ["A", "X", "A"], True),
        (["A", "A"], ["A", "X"], False),
    ],
)
def test_is_subsequence(reference, candidate, expected):
    assert is_subsequence(reference, candidate) is expected


# --- engine aggregation interaction -----------------------------------------------


def test_none_verdicts_are_excluded_from_pass_rate_but_not_from_mean():
    """The property the not-applicable verdict relies on, asserted at its source."""
    from eval_harness.engine import EvalEngine

    item = EvalItem(id="i", inputs={})
    results = [
        ItemResult(item=item, output=TargetOutput("a"), scores=[ScoreResult("s", value=0.0, passed=None)]),
        ItemResult(item=item, output=TargetOutput("b"), scores=[ScoreResult("s", value=1.0, passed=True)]),
    ]
    aggregate = EvalEngine._aggregate(results)["s"]
    assert aggregate.pass_rate == 1.0  # the None verdict is not counted as a failure
    assert aggregate.mean == 0.5  # but its value still moves the mean


# --- helpers used above are themselves exercised ----------------------------------


def test_helpers_build_the_step_kinds_they_claim():
    assert tool_call("t").kind == "tool_call"
    assert observation("x").kind == "tool_observation"
    assert tool_error("t").kind == "tool_error"
    assert final("d").kind == "final"
    assert isinstance(run_result(TargetOutput("a")), RunResult)
