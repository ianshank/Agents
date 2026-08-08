"""Test Matrix: All eval tools x standardized metrics.

Each component is tested across 8 metric dimensions:
  M1 - Correctness    : produces expected output for known inputs
  M2 - Edge Cases     : handles null / empty / malformed input gracefully
  M3 - Type Safety    : returns correct types (ScoreResult, JudgeVerdict, etc.)
  M4 - Interface      : implements the ABC contract (Scorer, Judge, DatasetSource...)
  M5 - Determinism    : same input -> same output (for deterministic components)
  M6 - Error Handling : raises or degrades gracefully on bad config / input
  M7 - Registry       : registered under expected key + aliases resolve
  M8 - Composability  : works inside the engine pipeline end-to-end

Run: pytest tests/test_matrix_eval_tools.py -v --tb=short
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from eval_harness.config import EvalConfig
from eval_harness.core.interfaces import DatasetSource, Judge, ResultSink, Scorer, TargetRunner
from eval_harness.core.types import (
    EvalItem,
    ItemResult,
    JudgeVerdict,
    RunContext,
    RunResult,
    ScoreAggregate,
    ScoreResult,
    TargetOutput,
)
from eval_harness.engine import EvalEngine
from eval_harness.gating import evaluate_gate
from eval_harness.plugins import DATASETS, JUDGES, SCORERS, SINKS, TARGETS, bootstrap
from tests import _trajectory_helpers as traj

bootstrap()

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

ITEM_NORMAL = EvalItem(id="t1", inputs={"q": "hello world"}, expected="hello world")
ITEM_EMPTY = EvalItem(id="t2", inputs={}, expected="")
ITEM_NONE_EXPECTED = EvalItem(id="t3", inputs={"q": "test"}, expected=None)
ITEM_UNICODE = EvalItem(id="t4", inputs={"q": "🎉 café résumé"}, expected="🎉 café résumé")
ITEM_JSON = EvalItem(
    id="t5",
    inputs={"q": "json test"},
    expected='{"a": 1, "b": 2}',
)

OUT_NORMAL = TargetOutput(output="hello world")
OUT_EMPTY = TargetOutput(output="")
OUT_NONE = TargetOutput(output=None)
OUT_UNICODE = TargetOutput(output="🎉 café résumé")
OUT_JSON_DICT = TargetOutput(output={"a": 1, "b": 2, "c": 3})
OUT_JSON_STR = TargetOutput(output='{"a": 1, "b": 2}')
OUT_INVALID_JSON = TargetOutput(output="not json {{{")
OUT_MISMATCH = TargetOutput(output="goodbye world")
OUT_PARTIAL = TargetOutput(output="hello")

CTX = RunContext(config=None)
MOCK_JUDGE = JUDGES.create("mock", {"default_score": 0.8})
CTX_WITH_JUDGE = RunContext(config=None, judge=MOCK_JUDGE)


# ============================================================================
# M7 - Registry: all expected keys are present, aliases resolve
# ============================================================================


class TestM7Registry:
    """M7 - Every component is registered under expected keys and aliases resolve."""

    @pytest.mark.parametrize(
        "name",
        ["mock", "openai", "anthropic", "bedrock", "phoenix_evals"],
        ids=lambda n: f"judge:{n}",
    )
    def test_judge_registered(self, name: str) -> None:
        assert name in JUDGES

    @pytest.mark.parametrize(
        "alias,canonical",
        [("deterministic", "mock"), ("claude", "anthropic"), ("phoenix-evals", "phoenix_evals")],
    )
    def test_judge_alias(self, alias: str, canonical: str) -> None:
        assert JUDGES.resolve(alias) == canonical

    @pytest.mark.parametrize(
        "name",
        ["exact_match", "contains", "regex_match", "json_keys", "llm_judge", "weighted", "autoevals"],
        ids=lambda n: f"scorer:{n}",
    )
    def test_scorer_registered(self, name: str) -> None:
        assert name in SCORERS

    @pytest.mark.parametrize(
        "alias,canonical",
        [
            ("exact", "exact_match"),
            ("regex", "regex_match"),
            ("composite", "weighted"),
            ("ensemble", "weighted"),
            ("llm-judge", "llm_judge"),
            ("judge", "llm_judge"),
            ("schema_keys", "json_keys"),
        ],
    )
    def test_scorer_alias(self, alias: str, canonical: str) -> None:
        assert SCORERS.resolve(alias) == canonical

    @pytest.mark.parametrize("name", ["inline", "jsonl", "csv", "parquet", "langfuse", "braintrust"])
    def test_dataset_registered(self, name: str) -> None:
        assert name in DATASETS

    @pytest.mark.parametrize("name", ["echo", "callable", "model"])
    def test_target_registered(self, name: str) -> None:
        assert name in TARGETS

    @pytest.mark.parametrize("name", ["console", "json_file", "html_file", "langfuse", "phoenix", "braintrust"])
    def test_sink_registered(self, name: str) -> None:
        assert name in SINKS


# ============================================================================
# M4 - Interface compliance: ABC contract
# ============================================================================


class TestM4Interface:
    """M4 - All registered classes implement the expected ABC."""

    @pytest.mark.parametrize("name", JUDGES.names())
    def test_judge_is_judge(self, name: str) -> None:
        assert issubclass(JUDGES.get(name), Judge)

    @pytest.mark.parametrize("name", SCORERS.names())
    def test_scorer_is_scorer(self, name: str) -> None:
        assert issubclass(SCORERS.get(name), Scorer)

    @pytest.mark.parametrize("name", DATASETS.names())
    def test_dataset_is_dataset_source(self, name: str) -> None:
        assert issubclass(DATASETS.get(name), DatasetSource)

    @pytest.mark.parametrize("name", TARGETS.names())
    def test_target_is_target_runner(self, name: str) -> None:
        assert issubclass(TARGETS.get(name), TargetRunner)

    @pytest.mark.parametrize("name", SINKS.names())
    def test_sink_is_result_sink(self, name: str) -> None:
        assert issubclass(SINKS.get(name), ResultSink)


# ============================================================================
# JUDGES
# ============================================================================


class TestMockJudge:
    """Mock judge test matrix."""

    def test_m1_correctness_default_score(self) -> None:
        j = JUDGES.create("mock", {"default_score": 0.75})
        v = j.evaluate("any prompt")
        assert v.score == 0.75
        assert v.reasoning == "default"

    def test_m1_correctness_rule_match(self) -> None:
        j = JUDGES.create("mock", {"rules": [{"contains": "password", "score": 0.3}]})
        v = j.evaluate("reset password please")
        assert v.score == 0.3
        assert "password" in v.reasoning

    def test_m1_correctness_first_rule_wins(self) -> None:
        j = JUDGES.create("mock", {"rules": [{"contains": "a", "score": 0.1}, {"contains": "b", "score": 0.9}]})
        v = j.evaluate("ab")
        assert v.score == 0.1  # first match wins

    def test_m2_edge_empty_prompt(self) -> None:
        j = JUDGES.create("mock", {"default_score": 1.0})
        v = j.evaluate("")
        assert v.score == 1.0

    def test_m2_edge_empty_rules(self) -> None:
        j = JUDGES.create("mock", {"rules": []})
        v = j.evaluate("anything")
        assert v.score == 1.0

    def test_m3_type_safety(self) -> None:
        j = JUDGES.create("mock", {"default_score": 0.5})
        v = j.evaluate("test")
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)
        assert isinstance(v.reasoning, str)
        assert isinstance(v.raw, dict)

    def test_m5_determinism(self) -> None:
        j = JUDGES.create("mock", {"default_score": 0.5, "rules": [{"contains": "x", "score": 0.9}]})
        results = [j.evaluate("x marks the spot") for _ in range(10)]
        assert all(r.score == results[0].score for r in results)

    def test_m6_error_string_score_coerced(self) -> None:
        """Score from config could be string '0.5' — should be float-coerced."""
        j = JUDGES.create("mock", {"default_score": "0.5"})  # type: ignore[arg-type]
        v = j.evaluate("test")
        assert v.score == 0.5
        assert isinstance(v.score, float)


# ============================================================================
# SCORERS
# ============================================================================


class TestExactMatchScorer:
    def test_m1_correctness_match(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_mismatch(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        r = s.score(ITEM_NORMAL, OUT_MISMATCH, CTX)
        assert r.value == 0.0 and r.passed is False

    def test_m1_case_insensitive(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em", "case_sensitive": False})
        item = EvalItem(id="ci", inputs={}, expected="HELLO")
        out = TargetOutput(output="hello")
        r = s.score(item, out, CTX)
        assert r.value == 1.0

    def test_m1_strip_whitespace(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em", "strip": True})
        item = EvalItem(id="ws", inputs={}, expected="hello")
        out = TargetOutput(output="  hello  ")
        assert s.score(item, out, CTX).value == 1.0

    def test_m2_edge_empty_strings(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        assert s.score(ITEM_EMPTY, OUT_EMPTY, CTX).value == 1.0

    def test_m2_edge_none_expected(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        r = s.score(ITEM_NONE_EXPECTED, TargetOutput(output="None"), CTX)
        # None → "None" via _as_text; should match string "None"
        assert isinstance(r.value, float)

    def test_m2_edge_unicode(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        assert s.score(ITEM_UNICODE, OUT_UNICODE, CTX).value == 1.0

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert isinstance(r, ScoreResult)
        assert r.name == "em"
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("exact_match", {"name": "em"})
        results = [s.score(ITEM_NORMAL, OUT_PARTIAL, CTX).value for _ in range(20)]
        assert len(set(results)) == 1


class TestContainsScorer:
    def test_m1_correctness_present(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "hello"})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 1.0

    def test_m1_correctness_absent(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "xyz"})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 0.0

    def test_m1_case_insensitive_default(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "HELLO"})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 1.0

    def test_m1_case_sensitive(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "HELLO", "case_sensitive": True})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 0.0

    def test_m2_edge_empty_substring(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": ""})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 1.0

    def test_m2_edge_empty_output(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "hello"})
        assert s.score(ITEM_NORMAL, OUT_EMPTY, CTX).value == 0.0

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "x"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert isinstance(r, ScoreResult)


class TestRegexMatchScorer:
    def test_m1_correctness_match(self) -> None:
        s = SCORERS.create("regex_match", {"name": "rx", "pattern": r"hel{2}o"})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 1.0

    def test_m1_correctness_no_match(self) -> None:
        s = SCORERS.create("regex_match", {"name": "rx", "pattern": r"^goodbye$"})
        assert s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value == 0.0

    def test_m2_edge_match_everything(self) -> None:
        s = SCORERS.create("regex_match", {"name": "rx", "pattern": ".*"})
        assert s.score(ITEM_NORMAL, OUT_EMPTY, CTX).value == 1.0

    def test_m6_error_invalid_regex(self) -> None:
        with pytest.raises(re.error):
            SCORERS.create("regex_match", {"name": "rx", "pattern": "[invalid"})


class TestJsonKeysScorer:
    def test_m1_correctness_all_present(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a", "b"]})
        assert s.score(ITEM_JSON, OUT_JSON_STR, CTX).value == 1.0

    def test_m1_correctness_partial(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a", "x"]})
        r = s.score(ITEM_JSON, OUT_JSON_STR, CTX)
        assert r.value == 0.5
        assert r.passed is False

    def test_m1_correctness_dict_output(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a", "c"]})
        assert s.score(ITEM_JSON, OUT_JSON_DICT, CTX).value == 1.0

    def test_m2_edge_no_required_keys(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": []})
        assert s.score(ITEM_JSON, OUT_JSON_STR, CTX).value == 1.0

    def test_m2_edge_invalid_json(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a"]})
        r = s.score(ITEM_JSON, OUT_INVALID_JSON, CTX)
        assert r.value == 0.0
        assert "not valid JSON" in (r.comment or "")

    def test_m2_edge_non_dict_json(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a"]})
        r = s.score(ITEM_JSON, TargetOutput(output="[1,2,3]"), CTX)
        assert r.value == 0.0
        assert "not an object" in (r.comment or "")


class TestLLMJudgeScorer:
    def test_m1_correctness_with_judge(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX_WITH_JUDGE)
        assert r.value == 0.8  # mock judge default_score
        assert r.passed is True  # 0.8 >= 0.5 threshold

    def test_m1_correctness_threshold(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj", "threshold": 0.9})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX_WITH_JUDGE)
        assert r.value == 0.8
        assert r.passed is False  # 0.8 < 0.9

    def test_m6_error_no_judge(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj"})
        with pytest.raises(RuntimeError, match="requires a judge"):
            s.score(ITEM_NORMAL, OUT_NORMAL, CTX)

    def test_m1_custom_template(self) -> None:
        s = SCORERS.create(
            "llm_judge",
            {
                "name": "lj",
                "prompt_template": "Rate: {output}",
            },
        )
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX_WITH_JUDGE)
        assert isinstance(r, ScoreResult)


class TestCompositeScorer:
    def test_m1_correctness_weighted_mean(self) -> None:
        s = SCORERS.create(
            "weighted",
            {
                "name": "comp",
                "components": [
                    {"type": "exact_match", "weight": 2.0},
                    {"type": "contains", "weight": 1.0, "params": {"substring": "xyz"}},
                ],
            },
        )
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        # exact_match=1.0 (w=2), contains=0.0 (w=1) → (2*1+1*0)/3 = 0.667
        assert abs(r.value - 2.0 / 3) < 0.001

    def test_m1_pass_threshold(self) -> None:
        s = SCORERS.create(
            "weighted",
            {
                "name": "comp",
                "pass_threshold": 0.5,
                "components": [
                    {"type": "exact_match", "weight": 1.0},
                    {"type": "contains", "weight": 1.0, "params": {"substring": "xyz"}},
                ],
            },
        )
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert r.passed is True  # 0.5 >= 0.5

    def test_m2_metadata_breakdown(self) -> None:
        s = SCORERS.create(
            "weighted",
            {
                "name": "comp",
                "components": [{"type": "exact_match", "weight": 1.0}],
            },
        )
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert "components" in r.metadata
        assert len(r.metadata["components"]) == 1

    def test_m6_error_no_components(self) -> None:
        with pytest.raises(ValueError, match="at least one component"):
            SCORERS.create("weighted", {"name": "comp", "components": []})

    def test_m6_error_negative_weight(self) -> None:
        with pytest.raises(ValueError, match="weight must be >= 0"):
            SCORERS.create(
                "weighted",
                {
                    "name": "comp",
                    "components": [{"type": "exact_match", "weight": -1.0}],
                },
            )

    def test_m6_error_zero_total_weight(self) -> None:
        with pytest.raises(ValueError, match="total weight must be > 0"):
            SCORERS.create(
                "weighted",
                {
                    "name": "comp",
                    "components": [{"type": "exact_match", "weight": 0.0}],
                },
            )


class TestAutoevalsScorer:
    def setup_class(self):
        pytest.importorskip("autoevals")

    def test_m1_correctness_levenshtein_match(self) -> None:
        s = SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert r.value == 1.0

    def test_m1_correctness_levenshtein_partial(self) -> None:
        s = SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})
        r = s.score(ITEM_NORMAL, OUT_MISMATCH, CTX)
        assert 0.0 < r.value < 1.0  # partial match

    def test_m6_error_unknown_scorer(self) -> None:
        with pytest.raises(ValueError, match="unknown autoevals scorer"):
            SCORERS.create("autoevals", {"name": "ae", "scorer": "NonExistentScorer"})

    def test_m6_error_missing_autoevals(self, monkeypatch) -> None:

        monkeypatch.setitem(sys.modules, "autoevals", None)
        with pytest.raises(RuntimeError, match="The 'autoevals' package is required"):
            SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})


# ============================================================================
# TRAJECTORY SCORERS (F-051)
# ============================================================================
#
# Matrix rows only: the discriminating scenario per scorer plus the shared
# cross-scorer dimensions. Behavioural depth stays in tests/test_trajectory_scorers.py
# and tests/test_trajectory_contracts.py — these cells are the index, not the depth.
# Assertions bind to `passed`/`value`, never `comment`: an arguments-only mismatch
# renders identical name lists in the comment.

#: All seven registered trajectory scorer names. Literal on purpose — the matrix
#: completeness guard cross-checks this file's declarations against the live registry
#: census, so a stale tuple fails loudly (a checked declaration, not a trusted list).
TRAJECTORY_SCORERS = (
    "trajectory_exact",
    "trajectory_in_order",
    "trajectory_any_order",
    "trajectory_precision_recall",
    "trajectory_step_efficiency",
    "trajectory_loop_detection",
    "trajectory_recovery",
)

#: The four reference-matching scorers (the other three grade the path on its own terms).
TRAJECTORY_REFERENCE_SCORERS = (
    "trajectory_exact",
    "trajectory_in_order",
    "trajectory_any_order",
    "trajectory_precision_recall",
)

TRAJECTORY_QUALITY_SCORERS = (
    "trajectory_step_efficiency",
    "trajectory_loop_detection",
    "trajectory_recovery",
)


def _score_trajectory(
    name: str,
    output: TargetOutput,
    expected: object = None,
    params: dict | None = None,
    **item_metadata: object,
) -> ScoreResult:
    scorer = SCORERS.create(name, params or {})
    return scorer.score(traj.item(expected, **item_metadata), output, CTX)


class TestTrajectoryExactScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_exact",)

    def test_m1_correctness_same_calls_same_order(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_exact", out, expected=["a", "b"])
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_extra_call_fails_exact(self) -> None:
        """The pair that separates exact from in_order: A,X,B fails exact."""
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("x"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_exact", out, expected=["a", "b"])
        assert r.value == 0.0 and r.passed is False


class TestTrajectoryInOrderScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_in_order",)

    def test_m1_correctness_subsequence_passes(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("x"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_in_order", out, expected=["a", "b"])
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_wrong_order_fails(self) -> None:
        out = traj.output_with(traj.tool_call("b"), traj.tool_call("a"))
        r = _score_trajectory("trajectory_in_order", out, expected=["a", "b"])
        assert r.value == 0.0 and r.passed is False


class TestTrajectoryAnyOrderScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_any_order",)

    def test_m1_correctness_order_ignored(self) -> None:
        out = traj.output_with(traj.tool_call("b"), traj.tool_call("a"))
        r = _score_trajectory("trajectory_any_order", out, expected=["a", "b"])
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_multiset_not_set(self) -> None:
        """A reference asking for two lookups is not satisfied by one."""
        out = traj.output_with(traj.tool_call("a"))
        r = _score_trajectory("trajectory_any_order", out, expected=["a", "a"])
        assert r.value == 0.0 and r.passed is False


class TestTrajectoryPrecisionRecallScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_precision_recall",)

    def test_m1_correctness_repeat_and_omission_report_separately(self) -> None:
        """One repeated required call + one omitted call: precision AND recall drop,
        and they are reported as separate numbers, not one blended verdict."""
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("a"))
        r = _score_trajectory("trajectory_precision_recall", out, expected=["a", "b"])
        assert r.metadata["precision"] == 0.5
        assert r.metadata["recall"] == 0.5
        assert r.value == 0.5 and r.passed is False  # default pass_threshold=1.0

    def test_m1_correctness_threshold_is_configurable(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("a"))
        r = _score_trajectory("trajectory_precision_recall", out, expected=["a", "b"], params={"pass_threshold": 0.5})
        assert r.value == 0.5 and r.passed is True


class TestTrajectoryStepEfficiencyScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_step_efficiency",)

    def test_m1_correctness_within_budget(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_step_efficiency", out, params={"budget": 4})
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_overrun_degrades_proportionally(self) -> None:
        out = traj.output_with(*(traj.tool_call(f"t{i}") for i in range(5)))
        r = _score_trajectory("trajectory_step_efficiency", out, params={"budget": 4})
        assert r.value == 0.8 and r.passed is False

    def test_m1_correctness_item_budget_overrides_param(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_step_efficiency", out, params={"budget": 4}, step_budget=1)
        assert r.value == 0.5 and r.passed is False


class TestTrajectoryLoopDetectionScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_loop_detection",)

    def test_m1_correctness_repeats_at_limit_pass(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("a"), traj.tool_call("b"))
        r = _score_trajectory("trajectory_loop_detection", out, params={"max_repeats": 2})
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_exceeding_limit_fails(self) -> None:
        out = traj.output_with(traj.tool_call("a"), traj.tool_call("a"), traj.tool_call("a"))
        r = _score_trajectory("trajectory_loop_detection", out, params={"max_repeats": 2})
        assert r.value == 0.0 and r.passed is False


class TestTrajectoryRecoveryScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("trajectory_recovery",)

    def test_m1_correctness_hallucinated_success_fails(self) -> None:
        out = traj.output_with(traj.tool_error("db"), traj.final())
        r = _score_trajectory("trajectory_recovery", out)
        assert r.value == 0.0 and r.passed is False

    def test_m1_correctness_retry_recovers(self) -> None:
        out = traj.output_with(traj.tool_error("db"), traj.tool_call("db"), traj.final())
        r = _score_trajectory("trajectory_recovery", out)
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_honest_stop_is_not_a_success_claim(self) -> None:
        out = traj.output_with(traj.tool_error("db"), traj.final(failed=True))
        r = _score_trajectory("trajectory_recovery", out)
        assert r.value == 1.0 and r.passed is True


class TestTrajectoryScorersShared:
    """Cross-scorer dimensions, parametrized over all seven trajectory scorers."""

    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = TRAJECTORY_SCORERS

    #: Per-scorer (params, expected) that make a normal 1-call trajectory score PASS,
    #: so the M3 assertions see a real bool verdict rather than a not-applicable None.
    _M3_SETUP: ClassVar[dict[str, tuple[dict, list | None]]] = {
        "trajectory_exact": ({}, ["a"]),
        "trajectory_in_order": ({}, ["a"]),
        "trajectory_any_order": ({}, ["a"]),
        "trajectory_precision_recall": ({}, ["a"]),
        "trajectory_step_efficiency": ({"budget": 4}, None),
        "trajectory_loop_detection": ({}, None),
        "trajectory_recovery": ({}, None),
    }

    @pytest.mark.parametrize("name", TRAJECTORY_SCORERS)
    def test_m2_edge_missing_trajectory_is_not_applicable(self, name: str) -> None:
        r = _score_trajectory(name, TargetOutput(output="text only"))
        assert r.passed is None and r.value == 0.0

    @pytest.mark.parametrize("name", TRAJECTORY_SCORERS)
    def test_m2_edge_on_missing_sets_the_emitted_value(self, name: str) -> None:
        r = _score_trajectory(name, TargetOutput(output="text only"), params={"on_missing": 0.5})
        assert r.passed is None and r.value == 0.5

    @pytest.mark.parametrize("name", TRAJECTORY_REFERENCE_SCORERS)
    def test_m2_edge_missing_reference_is_not_applicable(self, name: str) -> None:
        out = traj.output_with(traj.tool_call("a"))
        r = _score_trajectory(name, out, expected=None)
        assert r.passed is None

    @pytest.mark.parametrize("name", TRAJECTORY_QUALITY_SCORERS)
    def test_m2_edge_empty_trajectory_passes_quality_scorers(self, name: str) -> None:
        out = TargetOutput(output="x", trajectory=traj.trajectory())
        r = _score_trajectory(name, out, params={"budget": 4} if name == "trajectory_step_efficiency" else {})
        assert r.passed is True

    def test_m2_edge_empty_trajectory_fails_a_nonempty_reference(self) -> None:
        out = TargetOutput(output="x", trajectory=traj.trajectory())
        r = _score_trajectory("trajectory_exact", out, expected=["a"])
        assert r.value == 0.0 and r.passed is False

    @pytest.mark.parametrize("name", TRAJECTORY_SCORERS)
    def test_m3_type_safety(self, name: str) -> None:
        params, expected = self._M3_SETUP[name]
        out = traj.output_with(traj.tool_call("a"), traj.final())
        r = _score_trajectory(name, out, expected=expected, params=params)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)
        assert isinstance(r.metadata, dict)

    @pytest.mark.parametrize("name", TRAJECTORY_SCORERS)
    def test_m5_determinism_with_set_bearing_arguments(self, name: str) -> None:
        """Same-process stability over a set-valued argument (unordered on purpose).

        The cross-interpreter, cross-PYTHONHASHSEED canonicalisation property is pinned
        by real subprocesses in tests/test_trajectory_contracts.py; duplicating those
        spawns here would buy nothing. This cell asserts the scorer level: repeat
        scoring of one output is verdict-identical.
        """
        params, expected = self._M3_SETUP[name]
        out = traj.output_with(traj.tool_call("a", {"tags": {"x", "y", "z"}}), traj.final())
        results = [_score_trajectory(name, out, expected=expected, params=params) for _ in range(10)]
        verdicts = {(r.value, r.passed, r.comment) for r in results}
        assert len(verdicts) == 1

    @pytest.mark.parametrize(
        "name,params,exc",
        [
            ("trajectory_step_efficiency", {"count": "bogus"}, ValueError),
            ("trajectory_step_efficiency", {"budget": 0}, ValueError),
            ("trajectory_loop_detection", {"max_repeats": 0}, ValueError),
            # ValueError requires a non-numeric *string*; None raises TypeError instead.
            ("trajectory_exact", {"on_missing": "abc"}, ValueError),
            ("trajectory_exact", {"max_depth": 0}, ValueError),
            # Unknown kwarg raises from _TrajectoryScorer.__init__ (kwargs-free base);
            # also pinned by test_trajectory_integration's strict-config test.
            ("trajectory_exact", {"not_a_param": 1}, TypeError),
        ],
    )
    def test_m6_error_bad_config_is_rejected_at_construction(
        self, name: str, params: dict, exc: type[Exception]
    ) -> None:
        with pytest.raises(exc):
            SCORERS.create(name, params)


# ============================================================================
# DATASETS
# ============================================================================


class TestInlineDataset:
    def test_m1_correctness_loads(self) -> None:
        ds = DATASETS.create(
            "inline",
            {
                "items": [
                    {"id": "q1", "inputs": {"q": "test"}, "expected": "answer"},
                    {"id": "q2", "inputs": {"q": "test2"}, "expected": "answer2"},
                ]
            },
        )
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].id == "q1"
        assert items[0].expected == "answer"

    def test_m2_edge_empty_items(self) -> None:
        ds = DATASETS.create("inline", {"items": []})
        assert list(ds.load()) == []

    def test_m3_type_safety(self) -> None:
        ds = DATASETS.create("inline", {"items": [{"id": "t", "inputs": {}}]})
        items = list(ds.load())
        assert isinstance(items[0], EvalItem)


class TestJsonlDataset:
    def test_m1_correctness(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text(
            '{"id":"a","inputs":{"q":"hello"},"expected":"hi"}\n{"id":"b","inputs":{"q":"bye"},"expected":"goodbye"}\n'
        )
        ds = DATASETS.create("jsonl", {"path": str(p)})
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].id == "a"

    def test_m2_edge_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        ds = DATASETS.create("jsonl", {"path": str(p)})
        assert list(ds.load()) == []


class TestCsvDataset:
    def test_m1_correctness(self, tmp_path: Path) -> None:
        p = tmp_path / "data.csv"
        p.write_text("id,question,expected\na,hello,hi\nb,bye,goodbye\n")
        ds = DATASETS.create("csv", {"path": str(p), "input_columns": ["question"]})
        items = list(ds.load())
        assert len(items) == 2
        assert items[0].inputs["question"] == "hello"

    def test_m2_edge_empty_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text("id,question,expected\n")
        ds = DATASETS.create("csv", {"path": str(p), "input_columns": ["question"]})
        assert list(ds.load()) == []


# ============================================================================
# TARGETS
# ============================================================================


class TestEchoTarget:
    def test_m1_correctness_full_echo(self) -> None:
        t = TARGETS.create("echo", {})
        out = t.run(ITEM_NORMAL)
        assert out.output == ITEM_NORMAL.inputs

    def test_m1_correctness_key_echo(self) -> None:
        t = TARGETS.create("echo", {"output_key": "q"})
        out = t.run(ITEM_NORMAL)
        assert out.output == "hello world"

    def test_m2_edge_missing_key(self) -> None:
        t = TARGETS.create("echo", {"output_key": "nonexistent"})
        out = t.run(ITEM_NORMAL)
        assert out.output is None

    def test_m3_type_safety(self) -> None:
        t = TARGETS.create("echo", {})
        out = t.run(ITEM_NORMAL)
        assert isinstance(out, TargetOutput)

    def test_m5_determinism(self) -> None:
        t = TARGETS.create("echo", {"output_key": "q"})
        results = [t.run(ITEM_NORMAL).output for _ in range(10)]
        assert all(r == results[0] for r in results)


# ============================================================================
# SINKS
# ============================================================================


def _make_run_result() -> RunResult:
    """Create a minimal RunResult for sink testing."""
    from datetime import datetime

    return RunResult(
        run_id="test-run-001",
        config_name="test-config",
        items=[
            ItemResult(
                item=ITEM_NORMAL,
                output=OUT_NORMAL,
                scores=[ScoreResult(name="exact_match", value=1.0, passed=True)],
            ),
        ],
        aggregate={"exact_match": ScoreAggregate(count=1, mean=1.0, pass_rate=1.0)},
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=datetime(2026, 1, 1, 0, 0, 1),
    )


class TestConsoleSink:
    def test_m1_correctness_no_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        s = SINKS.create("console", {"verbose": False})
        s.emit(_make_run_result())
        captured = capsys.readouterr()
        assert "test-run-001" in captured.out or "exact_match" in captured.out

    def test_m1_verbose_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        s = SINKS.create("console", {"verbose": True})
        s.emit(_make_run_result())
        captured = capsys.readouterr()
        assert len(captured.out) > 0


class TestJsonFileSink:
    def test_m1_correctness_writes_json(self, tmp_path: Path) -> None:
        out_path = tmp_path / "result.json"
        s = SINKS.create("json_file", {"path": str(out_path)})
        s.emit(_make_run_result())
        data = json.loads(out_path.read_text())
        assert data["run_id"] == "test-run-001"
        assert "items" in data
        assert "aggregate" in data

    def test_m3_type_safety_valid_json(self, tmp_path: Path) -> None:
        out_path = tmp_path / "result.json"
        s = SINKS.create("json_file", {"path": str(out_path)})
        s.emit(_make_run_result())
        data = json.loads(out_path.read_text())
        assert isinstance(data, dict)


class TestHtmlFileSink:
    def test_m1_correctness_writes_html(self, tmp_path: Path) -> None:
        out_path = tmp_path / "report.html"
        s = SINKS.create("html_file", {"path": str(out_path)})
        s.emit(_make_run_result())
        content = out_path.read_text()
        assert "<html" in content.lower()
        assert "test-run-001" in content

    def test_m1_custom_title(self, tmp_path: Path) -> None:
        out_path = tmp_path / "report.html"
        s = SINKS.create("html_file", {"path": str(out_path), "title": "My Report"})
        s.emit(_make_run_result())
        content = out_path.read_text()
        assert "My Report" in content


# ============================================================================
# GATING
# ============================================================================


class TestGating:
    def test_m1_correctness_gate_pass(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        gate = GateConfig.model_validate({"rules": [{"score": "exact_match", "metric": "mean", "min": 0.5}]})
        run = _make_run_result()
        result = evaluate_gate(gate, run)
        assert result.passed is True

    def test_m1_correctness_gate_fail(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        gate = GateConfig.model_validate({"rules": [{"score": "exact_match", "metric": "mean", "min": 1.5}]})
        run = _make_run_result()
        result = evaluate_gate(gate, run)
        assert result.passed is False

    def test_m2_edge_no_rules(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        result = evaluate_gate(GateConfig(rules=[]), _make_run_result())
        assert result.passed is True

    def test_m2_edge_none_gate(self) -> None:
        from eval_harness.gating import evaluate_gate

        result = evaluate_gate(None, _make_run_result())
        assert result.passed is True


# ============================================================================
# M8 - Composability: full engine pipeline
# ============================================================================

#: The machine-readable index of every M8 pipeline. The tests below RUN these configs;
#: tests/test_matrix_coverage.py IMPORTS this constant and reads each component's kind
#: from the validated config's typed fields (never from bare "type" string literals,
#: which are ambiguous — `braintrust`/`langfuse` are registered as both a dataset and
#: a sink). Sink paths are placeholders, overridden per-test with tmp_path.
PIPELINES: dict[str, dict] = {
    "echo_exact_match": {
        "schema_version": "1.0",
        "run": {"name": "matrix-test", "seed": 42},
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {"id": "m1", "inputs": {"q": "hello"}, "expected": "hello"},
                    {"id": "m2", "inputs": {"q": "world"}, "expected": "world"},
                ],
            },
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [
            {"type": "exact_match", "params": {"name": "em"}},
            {"type": "contains", "params": {"name": "c", "substring": "hello"}},
        ],
        "judge": {"type": "mock", "params": {"default_score": 0.95}},
        "sinks": [{"type": "json_file", "params": {"path": "PLACEHOLDER.json"}}],
        "gate": {"rules": [{"score": "em", "metric": "mean", "min": 0.9}]},
    },
    "llm_judge": {
        "schema_version": "1.0",
        "run": {"name": "judge-test", "seed": 1},
        "dataset": {
            "type": "inline",
            "params": {"items": [{"id": "j1", "inputs": {"q": "test"}, "expected": "test"}]},
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "llm_judge", "params": {"name": "quality"}}],
        "judge": {"type": "mock", "params": {"default_score": 0.7}},
        "sinks": [{"type": "console"}],
    },
    "weighted": {
        "schema_version": "1.0",
        "run": {"name": "composite-test", "seed": 1},
        "dataset": {
            "type": "inline",
            "params": {"items": [{"id": "c1", "inputs": {"q": "hello"}, "expected": "hello"}]},
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [
            {
                "type": "weighted",
                "params": {
                    "name": "combo",
                    "components": [
                        {"type": "exact_match", "weight": 2.0},
                        {"type": "contains", "weight": 1.0, "params": {"substring": "hello"}},
                    ],
                },
            }
        ],
        "judge": {"type": "mock"},
        "sinks": [{"type": "console"}],
    },
    "trajectory": {
        "schema_version": "1.0",
        "run": {"name": "matrix-trajectory", "seed": 7},
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {
                        "id": "traj1",
                        "inputs": {"question": "what is widget 42"},
                        # Full arguments on purpose: comparison includes arguments by
                        # default, and the demo SUT echoes the question verbatim into
                        # `q` — a names-only reference fails trajectory_exact.
                        "expected": {
                            "tool_calls": [
                                {"name": "search", "arguments": {"q": "what is widget 42"}},
                                {"name": "fetch", "arguments": {"id": "42"}},
                            ]
                        },
                        "metadata": {"step_budget": 4},
                    }
                ],
            },
        },
        "target": {"type": "callable", "params": {"path": "tests._sut:trajectory_demo"}},
        "scorers": [
            {"type": "trajectory_exact", "params": {}},
            {"type": "trajectory_in_order", "params": {}},
            {"type": "trajectory_any_order", "params": {}},
            {"type": "trajectory_precision_recall", "params": {}},
            {"type": "trajectory_step_efficiency", "params": {"budget": 4}},
            {"type": "trajectory_loop_detection", "params": {}},
            {"type": "trajectory_recovery", "params": {}},
        ],
        "judge": {"type": "mock"},
        "sinks": [{"type": "json_file", "params": {"path": "PLACEHOLDER.json"}}],
        "gate": {
            "rules": [
                {"score": "trajectory_in_order", "metric": "pass_rate", "min": 1.0},
                {"score": "trajectory_recovery", "metric": "pass_rate", "min": 1.0},
            ]
        },
    },
    "trajectory_mixed": {
        "schema_version": "1.0",
        "run": {"name": "matrix-trajectory-mixed", "seed": 7},
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {
                        "id": "mix1",
                        "inputs": {"question": "what is widget 42"},
                        "expected": {
                            "tool_calls": [
                                {"name": "search", "arguments": {"q": "what is widget 42"}},
                                {"name": "fetch", "arguments": {"id": "42"}},
                            ]
                        },
                    }
                ],
            },
        },
        "target": {"type": "callable", "params": {"path": "tests._sut:trajectory_demo"}},
        "scorers": [
            {"type": "trajectory_in_order", "params": {}},
            {"type": "contains", "params": {"name": "mentions_widget", "substring": "widget 42"}},
        ],
        "judge": {"type": "mock"},
        "sinks": [{"type": "console"}],
    },
}


class TestM8Composability:
    """M8 - End-to-end engine pipelines over the PIPELINES index."""

    MATRIX_KIND = "engine"

    def _run(self, name: str, tmp_path: Path | None = None) -> tuple[EvalConfig, RunResult, Path | None]:
        config_dict = copy.deepcopy(PIPELINES[name])
        out_path: Path | None = None
        for sink in config_dict.get("sinks", []):
            if sink.get("type") == "json_file":
                assert tmp_path is not None, f"pipeline {name!r} writes a file; pass tmp_path"
                out_path = tmp_path / f"{name}.json"
                sink.setdefault("params", {})["path"] = str(out_path)
        config = EvalConfig.model_validate(config_dict)
        return config, EvalEngine.from_config(config).run(), out_path

    def test_m8_full_pipeline_echo_exact_match(self, tmp_path: Path) -> None:
        """Echo target + exact_match scorer + mock judge + json_file sink."""
        _, result, out_json = self._run("echo_exact_match", tmp_path)

        # Verify the pipeline produced correct results
        assert result.config_name == "matrix-test"
        assert len(result.items) == 2
        assert result.aggregate["em"].mean == 1.0
        assert result.aggregate["em"].pass_rate == 1.0
        # contains("hello") matches item m1 but not m2
        assert result.aggregate["c"].mean == 0.5

        # Verify the sink wrote the file
        assert out_json is not None and out_json.exists()
        data = json.loads(out_json.read_text())
        assert data["run_id"] == result.run_id

    def test_m8_pipeline_with_llm_judge_scorer(self) -> None:
        """LLM judge scorer uses injected mock judge through ctx."""
        _, result, _ = self._run("llm_judge")
        assert result.aggregate["quality"].mean == 0.7

    def test_m8_pipeline_with_composite_scorer(self) -> None:
        """Composite scorer composes children inside the engine pipeline."""
        _, result, _ = self._run("weighted")
        assert result.aggregate["combo"].mean == 1.0

    def test_m8_trajectory_pipeline(self, tmp_path: Path) -> None:
        """All 7 trajectory scorers over the shipped trajectory-emitting callable,
        through config validation, the engine, a file sink and the gate."""
        config, result, out_json = self._run("trajectory", tmp_path)

        # The callable target swallows SUT exceptions into TargetOutput.error, so a
        # broken SUT would surface here as error text, not as a raised exception.
        assert result.items[0].output.error is None
        for name in TRAJECTORY_SCORERS:
            assert result.aggregate[name].pass_rate == 1.0, name

        assert out_json is not None
        data = json.loads(out_json.read_text())
        emitted = data["items"][0]
        assert "trajectory" in emitted, "the sink payload must carry the trajectory"
        assert len(emitted["trajectory"]["steps"]) == 6

        gate = evaluate_gate(config.gate, result)
        assert gate.passed is True

    def test_m8_trajectory_and_outcome_scorers_compose(self) -> None:
        """A trajectory scorer and a text scorer grade the same run side by side."""
        _, result, _ = self._run("trajectory_mixed")
        assert result.aggregate["trajectory_in_order"].pass_rate == 1.0
        assert result.aggregate["mentions_widget"].pass_rate == 1.0


# ============================================================================
# NEW COMPONENT MATRIX TESTS (HARDENED)
# ============================================================================

# Dynamic Test Data to replace hard-coded values
MOCK_API_KEY = "test-key"  # gitleaks:allow
MOCK_MODEL_ID_OPENAI = "gpt-4-turbo"
MOCK_MODEL_ID_ANTHROPIC = "claude-3-opus"
MOCK_MODEL_ID_BEDROCK = "anthropic.claude-v2"
MOCK_PROMPT = "Evaluate this output"
MOCK_REASONING = "The output is excellent"
MOCK_SCORE = 0.95
MOCK_REGION = "us-west-2"

# ----------------------------------------------------------------------------
# 1. JUDGES
# ----------------------------------------------------------------------------


class TestOpenAIJudge:
    def setup_class(self):
        pytest.importorskip("openai")

    def test_m1_correctness(self) -> None:
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING})
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_client.chat.completions.create.return_value = [mock_chunk]

        with patch.dict("sys.modules", {"openai": mock_openai}):
            j = JUDGES.create("openai", {"model": MOCK_MODEL_ID_OPENAI, "api_key": MOCK_API_KEY})
            v = j.evaluate(MOCK_PROMPT)
            assert v.score == MOCK_SCORE
            assert v.reasoning == MOCK_REASONING

    def test_m2_edge_malformed_json(self) -> None:
        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "invalid json {"
        mock_chunk.choices[0].delta.reasoning_content = None
        mock_client.chat.completions.create.return_value = [mock_chunk]

        with patch.dict("sys.modules", {"openai": mock_openai}):
            j = JUDGES.create("openai", {"model": MOCK_MODEL_ID_OPENAI, "api_key": MOCK_API_KEY})
            v = j.evaluate(MOCK_PROMPT)
            assert v.score == 0.0
            assert "Failed to parse" in v.reasoning or "Could not extract JSON" in v.reasoning

    def test_m6_error_rate_limit(self) -> None:
        import openai

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            "Rate limit", response=MagicMock(), body=None
        )
        mock_openai.RateLimitError = openai.RateLimitError

        with patch.dict("sys.modules", {"openai": mock_openai}):
            j = JUDGES.create("openai", {"model": MOCK_MODEL_ID_OPENAI, "api_key": MOCK_API_KEY})
            with pytest.raises(openai.RateLimitError):
                j.evaluate(MOCK_PROMPT)


class TestAnthropicJudge:
    def setup_class(self):
        pytest.importorskip("anthropic")

    def test_m1_correctness(self) -> None:
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING})
        mock_msg.content = [mock_block]
        mock_client.messages.create.return_value = mock_msg

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            j = JUDGES.create("anthropic", {"model": MOCK_MODEL_ID_ANTHROPIC, "api_key": MOCK_API_KEY})
            v = j.evaluate(MOCK_PROMPT)
            assert v.score == MOCK_SCORE
            assert v.reasoning == MOCK_REASONING

    def test_m6_error_api(self) -> None:
        import anthropic

        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic.APIError("API error", request=MagicMock(), body=None)
        mock_anthropic.APIError = anthropic.APIError

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            j = JUDGES.create("anthropic", {"model": MOCK_MODEL_ID_ANTHROPIC, "api_key": MOCK_API_KEY})
            with pytest.raises(anthropic.APIError):
                j.evaluate(MOCK_PROMPT)


class TestBedrockJudge:
    def setup_class(self):
        pytest.importorskip("boto3")

    def test_m1_correctness(self) -> None:
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        import json

        inner_json = json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING})
        payload = json.dumps({"content": [{"text": inner_json}]})

        mock_client.invoke_model.return_value = {"body": MagicMock(read=lambda: payload.encode("utf-8"))}

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            j = JUDGES.create("bedrock", {"model_id": MOCK_MODEL_ID_BEDROCK, "region": MOCK_REGION})
            v = j.evaluate(MOCK_PROMPT)
            assert v.score == MOCK_SCORE
            assert v.reasoning == MOCK_REASONING


class TestPhoenixEvalJudge:
    def setup_class(self):
        pass

    def test_m1_correctness(self) -> None:
        mock_px = MagicMock()
        mock_llm = MagicMock()
        mock_evaluator_cls = MagicMock()
        mock_px.LLM = mock_llm
        mock_px.ClassificationEvaluator = mock_evaluator_cls

        mock_evaluator = MagicMock()
        mock_evaluator_cls.return_value = mock_evaluator

        mock_result = MagicMock()
        mock_result.label = "pass"
        mock_result.score = 1.0
        mock_result.explanation = "pass"
        mock_evaluator.evaluate.return_value = [mock_result]

        with patch.dict("sys.modules", {"phoenix.evals": mock_px}):
            j = JUDGES.create("phoenix_evals", {"model": MOCK_MODEL_ID_OPENAI})
            v = j.evaluate("some prompt")
            assert v.score == 1.0
            assert v.reasoning == "pass"


# ----------------------------------------------------------------------------
# 2. DATASETS
# ----------------------------------------------------------------------------


class TestParquetDataset:
    def setup_class(self):
        pytest.importorskip("pandas")

    def test_m1_correctness(self, tmp_path) -> None:
        import pandas as pd

        df = pd.DataFrame([{"id": "ds-1", "question": "q1", "expected": "a1"}])
        p = tmp_path / "test_data.parquet"
        df.to_parquet(p)
        ds = DATASETS.create("parquet", {"path": p.as_posix(), "input_columns": ["question"]})
        items = list(ds.load())
        assert len(items) == 1
        assert items[0].id == "ds-1"

    def test_m6_missing_file(self) -> None:
        ds = DATASETS.create("parquet", {"path": "invalid-path-123.parquet"})
        with pytest.raises(FileNotFoundError):
            list(ds.load())


class TestLangfuseDataset:
    def setup_class(self):
        pytest.importorskip("langfuse")

    def test_m1_correctness(self) -> None:
        mock_lf_mod = MagicMock()
        mock_client = MagicMock()
        mock_lf_mod.Langfuse.return_value = mock_client
        mock_item = {"id": "lf-1", "inputs": {"q": "test"}, "expected": "ans"}
        mock_client.get_dataset_items.return_value = [mock_item]

        with patch.dict("sys.modules", {"langfuse": mock_lf_mod}):
            ds = DATASETS.create("langfuse", {"dataset_name": "test-langfuse-ds"})
            ds.attach_client(mock_client)  # type: ignore[attr-defined]
            items = list(ds.load())
            assert len(items) == 1
            assert items[0].id == "lf-1"


class TestBraintrustDataset:
    def setup_class(self):
        pytest.importorskip("braintrust")

    def test_m1_correctness(self) -> None:
        mock_bt = MagicMock()
        mock_ds = MagicMock()
        mock_bt.init_dataset.return_value = mock_ds
        mock_ds.__iter__.return_value = [{"id": "bt-1", "input": {"q": "test"}, "expected": "ans"}]

        with patch.dict("sys.modules", {"braintrust": mock_bt}):
            ds = DATASETS.create("braintrust", {"name": "test-braintrust-ds"})
            items = list(ds.load())
            assert len(items) == 1
            assert items[0].id == "bt-1"


# ----------------------------------------------------------------------------
# 3. TARGETS
# ----------------------------------------------------------------------------


class TestCallableTarget:
    def test_m1_correctness(self) -> None:
        t = TARGETS.create("callable", {"path": "json:dumps"})
        out = t.run(ITEM_NORMAL)
        assert out.output is not None
        assert isinstance(out.output, str)

    def test_m6_error(self) -> None:
        t = TARGETS.create("callable", {"path": "nonexistent.module_xyz:func_abc"})
        with pytest.raises(ImportError):
            t.run(ITEM_NORMAL)


class TestModelTarget:
    def test_m1_correctness(self) -> None:
        mock_client = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "mock answer"
        mock_client.chat.completions.create.return_value = [mock_chunk]

        t = TARGETS.create(
            "model",
            {"model": MOCK_MODEL_ID_OPENAI, "provider": "openai", "client": mock_client, "prompt_template": "{q}"},
        )
        out = t.run(ITEM_NORMAL)
        assert out.output == "mock answer"


# ----------------------------------------------------------------------------
# 4. SINKS
# ----------------------------------------------------------------------------


class TestLangfuseSink:
    def setup_class(self):
        pytest.importorskip("langfuse")

    def test_m1_correctness_and_m5_lifecycle(self) -> None:
        mock_lf_mod = MagicMock()
        mock_client = MagicMock()
        mock_lf_mod.Langfuse.return_value = mock_client
        with patch.dict("sys.modules", {"langfuse": mock_lf_mod}):
            s = SINKS.create("langfuse", {})
            s.attach_client(mock_client)  # type: ignore[attr-defined]
            s.emit(_make_run_result())
            mock_client.flush.assert_called()


class TestPhoenixSink:
    def setup_class(self):
        pytest.importorskip("phoenix")

    def test_m1_correctness(self) -> None:
        mock_px = MagicMock()
        with patch.dict("sys.modules", {"phoenix": mock_px}):
            s = SINKS.create("phoenix", {})
            s.emit(_make_run_result())
            # If it doesn't crash, we're good


class TestBraintrustSink:
    def setup_class(self):
        pytest.importorskip("braintrust")

    def test_m1_correctness(self) -> None:
        mock_bt = MagicMock()
        mock_logger = MagicMock()
        mock_bt.init_logger.return_value = mock_logger
        with patch.dict("sys.modules", {"braintrust": mock_bt}):
            s = SINKS.create("braintrust", {})
            s.emit(_make_run_result())
            s.close()  # type: ignore[attr-defined]
            mock_logger.flush.assert_called()
