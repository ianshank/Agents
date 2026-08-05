"""Behavioural tests for the seven trajectory scorers.

The scenarios in `openspec/changes/add-agent-trajectory-evaluation/specs/` are each
asserted here, plus the not-applicable path that keeps text-only targets from being
silently failed.
"""

from __future__ import annotations

import pytest

from eval_harness.core.types import RunContext, TargetOutput
from eval_harness.plugins import SCORERS
from tests._trajectory_helpers import final, item, observation, output_with, tool_call, tool_error

CTX = RunContext(config=None)

REGISTERED = (
    "trajectory_exact",
    "trajectory_in_order",
    "trajectory_any_order",
    "trajectory_precision_recall",
    "trajectory_step_efficiency",
    "trajectory_loop_detection",
    "trajectory_recovery",
)


def score(name: str, output: TargetOutput, expected=None, params=None, **item_metadata):
    scorer = SCORERS.create(name, params or {})
    return scorer.score(item(expected, **item_metadata), output, CTX)


# --- registration -----------------------------------------------------------------


@pytest.mark.parametrize("name", REGISTERED)
def test_registered_with_hyphenated_alias(name):
    assert name in SCORERS
    alias = name.replace("_", "-")
    assert SCORERS.resolve(alias) == name


@pytest.mark.parametrize("name", REGISTERED)
def test_default_score_name_matches_registration(name):
    assert SCORERS.create(name, {}).name == name


# --- the not-applicable path ------------------------------------------------------


@pytest.mark.parametrize("name", REGISTERED)
def test_missing_trajectory_is_not_applicable_not_a_failure(name):
    result = score(name, TargetOutput(output="just text"), expected=["a"])
    assert result.passed is None, "a text-only target must not be failed by a trajectory scorer"
    assert result.value == 0.0
    assert "not applicable" in (result.comment or "")


@pytest.mark.parametrize("name", REGISTERED)
def test_on_missing_value_is_configurable(name):
    result = score(name, TargetOutput(output="text"), expected=["a"], params={"on_missing": 0.5})
    assert result.value == 0.5
    assert result.passed is None


@pytest.mark.parametrize("name", ("trajectory_exact", "trajectory_in_order", "trajectory_any_order"))
def test_missing_reference_is_not_applicable(name):
    result = score(name, output_with(tool_call("a")), expected=None)
    assert result.passed is None
    assert "reference" in (result.comment or "")


def test_unparseable_reference_is_not_applicable():
    result = score("trajectory_exact", output_with(tool_call("a")), expected=[42])
    assert result.passed is None


@pytest.mark.parametrize("expected", ([{"name": "a"}], ["a"], {"tool_calls": ["a"]}))
def test_reference_shapes_are_all_accepted(expected):
    assert score("trajectory_exact", output_with(tool_call("a")), expected=expected).passed is True


# --- exact ------------------------------------------------------------------------


def test_exact_rejects_an_extra_call():
    """Spec: reference A then B, candidate A then X then B -> exact fails."""
    result = score("trajectory_exact", output_with(tool_call("A"), tool_call("X"), tool_call("B")), ["A", "B"])
    assert result.passed is False
    assert result.value == 0.0


def test_exact_accepts_the_same_calls_in_the_same_order():
    assert score("trajectory_exact", output_with(tool_call("A"), tool_call("B")), ["A", "B"]).passed is True


def test_exact_rejects_reordering():
    assert score("trajectory_exact", output_with(tool_call("B"), tool_call("A")), ["A", "B"]).passed is False


def test_exact_compares_arguments_by_default():
    out = output_with(tool_call("A", {"q": "x"}))
    assert score("trajectory_exact", out, [{"name": "A", "arguments": {"q": "y"}}]).passed is False
    assert score("trajectory_exact", out, [{"name": "A", "arguments": {"q": "x"}}]).passed is True


def test_exact_ignores_configured_volatile_fields():
    out = output_with(tool_call("A", {"q": "x", "req_id": "abc"}))
    expected = [{"name": "A", "arguments": {"q": "x", "req_id": "zzz"}}]
    assert score("trajectory_exact", out, expected, params={"ignore_fields": ["req_id"]}).passed is True


# --- in-order ---------------------------------------------------------------------


def test_in_order_tolerates_an_extra_call():
    """Spec: reference A then B, candidate A then X then B -> in-order passes."""
    result = score("trajectory_in_order", output_with(tool_call("A"), tool_call("X"), tool_call("B")), ["A", "B"])
    assert result.passed is True
    assert result.value == 1.0


def test_in_order_rejects_wrong_order():
    result = score("trajectory_in_order", output_with(tool_call("B"), tool_call("A")), ["A", "B"])
    assert result.passed is False
    assert "subsequence" in (result.comment or "")


def test_in_order_rejects_a_missing_call():
    assert score("trajectory_in_order", output_with(tool_call("A")), ["A", "B"]).passed is False


# --- any-order --------------------------------------------------------------------


def test_any_order_ignores_ordering():
    """Spec: reference A and B, candidate B and A -> any-order passes."""
    assert score("trajectory_any_order", output_with(tool_call("B"), tool_call("A")), ["A", "B"]).passed is True


def test_any_order_tolerates_extras():
    out = output_with(tool_call("X"), tool_call("B"), tool_call("A"))
    assert score("trajectory_any_order", out, ["A", "B"]).passed is True


def test_any_order_is_a_multiset_not_a_set():
    """Two required lookups are not satisfied by one."""
    assert score("trajectory_any_order", output_with(tool_call("A")), ["A", "A"]).passed is False
    assert score("trajectory_any_order", output_with(tool_call("A"), tool_call("A")), ["A", "A"]).passed is True


def test_any_order_names_the_missing_call():
    """Diagnostics report the canonical (normalised) name, not the name as written."""
    result = score("trajectory_any_order", output_with(tool_call("A")), ["A", "B"])
    assert "b" in (result.comment or "")


def test_diagnostics_report_canonical_names_under_case_sensitive_config():
    result = score(
        "trajectory_any_order",
        output_with(tool_call("A")),
        ["A", "B"],
        params={"case_sensitive_names": True},
    )
    assert "B" in (result.comment or "")


# --- precision / recall -----------------------------------------------------------


def test_duplicate_and_omission_reduce_precision_and_recall_separately():
    """Spec: a candidate repeating one required call and omitting another."""
    out = output_with(tool_call("A"), tool_call("A"))
    result = score("trajectory_precision_recall", out, ["A", "B"])
    assert result.metadata["precision"] == pytest.approx(0.5)
    assert result.metadata["recall"] == pytest.approx(0.5)
    assert result.passed is False


def test_perfect_overlap_scores_one():
    out = output_with(tool_call("A"), tool_call("B"))
    result = score("trajectory_precision_recall", out, ["A", "B"])
    assert result.value == pytest.approx(1.0)
    assert result.passed is True


def test_extra_work_lowers_precision_but_not_recall():
    out = output_with(tool_call("A"), tool_call("B"), tool_call("C"))
    result = score("trajectory_precision_recall", out, ["A", "B"])
    assert result.metadata["recall"] == pytest.approx(1.0)
    assert result.metadata["precision"] == pytest.approx(2 / 3)


def test_missing_work_lowers_recall_but_not_precision():
    result = score("trajectory_precision_recall", output_with(tool_call("A")), ["A", "B"])
    assert result.metadata["precision"] == pytest.approx(1.0)
    assert result.metadata["recall"] == pytest.approx(0.5)


def test_no_calls_against_a_reference_scores_zero():
    result = score("trajectory_precision_recall", output_with(final("done")), ["A"])
    assert result.value == 0.0


def test_empty_reference_and_empty_candidate_is_a_pass():
    result = score("trajectory_precision_recall", output_with(final("done")), [])
    assert result.value == pytest.approx(1.0)


def test_precision_recall_pass_threshold_is_configurable():
    out = output_with(tool_call("A"), tool_call("A"))
    assert score("trajectory_precision_recall", out, ["A", "B"], params={"pass_threshold": 0.4}).passed is True


# --- step efficiency --------------------------------------------------------------


def test_wasteful_but_correct_trajectory_is_visible():
    """Spec: fourteen steps against a four-step budget."""
    out = output_with(*[tool_call(f"t{i}") for i in range(14)])
    result = score("trajectory_step_efficiency", out, params={"budget": 4})
    assert result.passed is False
    assert result.value == pytest.approx(4 / 14)
    assert result.metadata == {"actual": 14, "budget": 4, "count": "tool_calls"}


def test_within_budget_scores_one():
    out = output_with(tool_call("a"), tool_call("b"))
    assert score("trajectory_step_efficiency", out, params={"budget": 4}).value == 1.0


def test_finishing_under_budget_is_not_rewarded_above_finishing_at_it():
    at_budget = output_with(tool_call("a"), tool_call("b"))
    under = output_with(tool_call("a"))
    params = {"budget": 2}
    assert score("trajectory_step_efficiency", at_budget, params=params).value == 1.0
    assert score("trajectory_step_efficiency", under, params=params).value == 1.0


def test_item_budget_overrides_the_configured_default():
    out = output_with(tool_call("a"), tool_call("b"), tool_call("c"))
    assert score("trajectory_step_efficiency", out, params={"budget": 10}, step_budget=2).passed is False


def test_absent_budget_is_not_applicable():
    result = score("trajectory_step_efficiency", output_with(tool_call("a")))
    assert result.passed is None
    assert "budget" in (result.comment or "")


def test_non_positive_item_budget_is_not_applicable():
    result = score("trajectory_step_efficiency", output_with(tool_call("a")), step_budget=0)
    assert result.passed is None


def test_counting_all_steps_instead_of_tool_calls():
    out = output_with(tool_call("a"), observation("x"), final("done"))
    assert score("trajectory_step_efficiency", out, params={"budget": 2, "count": "steps"}).passed is False
    assert score("trajectory_step_efficiency", out, params={"budget": 2}).passed is True


def test_invalid_step_efficiency_configuration_raises():
    with pytest.raises(ValueError, match="unknown count mode"):
        SCORERS.create("trajectory_step_efficiency", {"count": "nope"})
    with pytest.raises(ValueError, match="budget must be > 0"):
        SCORERS.create("trajectory_step_efficiency", {"budget": 0})


# --- loop detection ---------------------------------------------------------------


def test_a_loop_is_detected():
    out = output_with(tool_call("a"), tool_call("a"), tool_call("a"))
    result = score("trajectory_loop_detection", out, params={"max_repeats": 2})
    assert result.passed is False
    assert result.metadata["max_observed_repeats"] == 3
    assert "'a' repeated 3 times" in (result.comment or "")


def test_repeats_at_the_limit_pass():
    out = output_with(tool_call("a"), tool_call("a"))
    assert score("trajectory_loop_detection", out, params={"max_repeats": 2}).passed is True


def test_consecutive_mode_ignores_non_adjacent_repeats():
    out = output_with(tool_call("a"), tool_call("b"), tool_call("a"), tool_call("b"), tool_call("a"))
    assert score("trajectory_loop_detection", out, params={"max_repeats": 2}).passed is True


def test_total_mode_catches_non_adjacent_repeats():
    out = output_with(tool_call("a"), tool_call("b"), tool_call("a"), tool_call("b"), tool_call("a"))
    result = score("trajectory_loop_detection", out, params={"max_repeats": 2, "consecutive": False})
    assert result.passed is False
    assert result.metadata["max_observed_repeats"] == 3


def test_a_trajectory_with_no_calls_does_not_loop():
    assert score("trajectory_loop_detection", output_with(final("done"))).passed is True


def test_differing_arguments_break_a_loop():
    out = output_with(tool_call("a", {"p": 1}), tool_call("a", {"p": 2}), tool_call("a", {"p": 3}))
    assert score("trajectory_loop_detection", out, params={"max_repeats": 2}).passed is True


def test_invalid_loop_configuration_raises():
    with pytest.raises(ValueError, match="max_repeats must be >= 1"):
        SCORERS.create("trajectory_loop_detection", {"max_repeats": 0})


# --- recovery ---------------------------------------------------------------------


def test_false_success_after_a_tool_error_fails():
    """Spec: the agent proceeds as though the failed call succeeded."""
    out = output_with(tool_call("a"), tool_error("a"), final("all done"))
    result = score("trajectory_recovery", out)
    assert result.passed is False
    assert "a" in result.metadata["unrecovered_tools"]


def test_a_retry_after_a_tool_error_passes():
    out = output_with(tool_call("a"), tool_error("a"), tool_call("a"), observation("ok"), final("done"))
    assert score("trajectory_recovery", out).passed is True


def test_a_fallback_to_another_tool_passes():
    out = output_with(tool_call("a"), tool_error("a"), tool_call("b"), observation("ok"), final("done"))
    assert score("trajectory_recovery", out).passed is True


def test_stopping_without_claiming_success_passes():
    out = output_with(tool_call("a"), tool_error("a"), final("could not complete", failed=True))
    assert score("trajectory_recovery", out).passed is True


def test_erroring_with_no_terminal_step_passes():
    out = output_with(tool_call("a"), tool_error("a"))
    assert score("trajectory_recovery", out).passed is True


def test_a_clean_trajectory_passes_and_counts_zero_errors():
    result = score("trajectory_recovery", output_with(tool_call("a"), observation("ok"), final("done")))
    assert result.passed is True
    assert result.metadata["tool_errors"] == 0


def test_an_error_without_a_tool_call_is_still_reported():
    from eval_harness.core.types import TrajectoryStep

    out = output_with(TrajectoryStep(kind="tool_error", content="boom"), final("done"))
    assert score("trajectory_recovery", out).metadata["unrecovered_tools"] == ["<unknown tool>"]


def test_failure_key_is_configurable():
    from eval_harness.core.types import TrajectoryStep

    out = output_with(
        tool_error("a"),
        TrajectoryStep(kind="final", content="stopped", metadata={"aborted": True}),
    )
    assert score("trajectory_recovery", out, params={"failure_key": "aborted"}).passed is True


def test_reference_accepts_tool_call_records_directly():
    """A reference may be built from ToolCallRecord objects, not only plain data."""
    from eval_harness.core.types import ToolCallRecord

    out = output_with(tool_call("A", {"q": "x"}))
    assert score("trajectory_exact", out, [ToolCallRecord("A", {"q": "x"})]).passed is True
