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

from eval_harness import plugins as _plugins_module
from eval_harness.config import EvalConfig
from eval_harness.core.interfaces import DatasetSource, Judge, ResultSink, Scorer, TargetRunner
from eval_harness.core.registry import Registry
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
from tests._m8_probe import ExecutionLedger, probe
from tests._matrix_coverage import format_vacuous, pipeline_vacuous

bootstrap()

# The committed registry surface (names + aliases, flat per kind) and the live
# registries it must resolve against, discovered dynamically by `.kind` so a future
# sixth registry is picked up without a code change here.
_REGISTRY_BASELINE: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "plugin_registry_baseline.json").read_text(encoding="utf-8")
)
_BASELINE_PAIRS = [(kind, key) for kind, keys in sorted(_REGISTRY_BASELINE.items()) for key in keys]
_LIVE_REGISTRIES: dict[str, Registry] = {
    obj.kind: obj for obj in vars(_plugins_module).values() if isinstance(obj, Registry)
}

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
# M7 - Registry: every committed surface key resolves in its live registry
# ============================================================================


class TestM7Registry:
    """M7 - Derived from the committed registry baseline, never a hand list.

    The old hardcoded name/alias lists went stale by seven scorers the day F-051
    registered them — the manual-list-vs-derived-reality defect F-050/F-052 closed
    elsewhere. `tests/plugin_registry_baseline.json` stores names and aliases MERGED
    FLAT per kind, so what this class asserts is *resolvability*: every committed key
    is accepted by the live registry of its kind and resolves to a canonical name.
    The directed alias→canonical PAIRING (a flat baseline cannot see a repointed
    alias, and `Registry._aliases` assignment has no duplicate guard) is frozen by
    exact equality against FROZEN_ALIAS_MAP in tests/test_matrix_coverage.py.

    In-process reads are safe for THIS direction only: canonical registrations are
    add-only (`register_class` raises on a differing duplicate), so pollution from
    test doubles can only ADD live keys, never mask a baseline key. The opposite
    direction — live ⊆ baseline — is the fresh-subprocess surface guard's job in
    tests/test_plugin_registry_surface.py; do not "simplify" these into one.
    """

    MATRIX_REGISTRY = True

    @pytest.mark.parametrize("kind,key", _BASELINE_PAIRS, ids=[f"{k}:{n}" for k, n in _BASELINE_PAIRS])
    def test_committed_key_resolves_in_its_live_registry(self, kind: str, key: str) -> None:
        assert kind in _LIVE_REGISTRIES, f"baseline kind {kind!r} has no live registry"
        registry = _LIVE_REGISTRIES[kind]
        assert key in registry, f"{kind} key {key!r} no longer resolves"
        assert registry.resolve(key) in registry.names()

    def test_baseline_is_populated(self) -> None:
        """Vacuity guard: an empty or truncated baseline must fail, not pass silently."""
        assert len(_BASELINE_PAIRS) > 40
        assert set(_REGISTRY_BASELINE) == set(_LIVE_REGISTRIES)


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
        # Scorer is a Protocol; check explicit MRO inheritance for all registered scorers
        cls = SCORERS.get(name)
        assert Scorer in cls.__mro__

    def test_scorer_protocol_duck_typing(self) -> None:
        class DuckScorer:
            name: str = "duck"

            def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
                return ScoreResult(name=self.name, value=1.0)

            def uses_judge(self) -> bool:
                return False

        assert isinstance(DuckScorer(), Scorer)

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

    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("mock",)

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
        """Score from config could be string '0.5' — should be float-coerced.

        No `type: ignore` needed: `Registry.create` takes an untyped `dict`, so there is
        no arg-type check to suppress. The suppression that used to sit here was dead —
        invisible because the root config leaves `warn_unused_ignores` off.
        """
        j = JUDGES.create("mock", {"default_score": "0.5"})
        v = j.evaluate("test")
        assert v.score == 0.5
        assert isinstance(v.score, float)


# ============================================================================
# SCORERS
# ============================================================================


class TestExactMatchScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("exact_match",)

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

    def test_m6_error_unknown_param_rejected(self) -> None:
        with pytest.raises(TypeError):
            SCORERS.create("exact_match", {"name": "em", "not_a_param": 1})


class TestContainsScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("contains",)

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

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("contains", {"name": "c", "substring": "hello"})
        results = [s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value for _ in range(10)]
        assert len(set(results)) == 1

    def test_m6_error_unknown_param_rejected(self) -> None:
        with pytest.raises(TypeError):
            SCORERS.create("contains", {"name": "c", "not_a_param": 1})


class TestRegexMatchScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("regex_match",)

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

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("regex_match", {"name": "rx", "pattern": r"\w+"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("regex_match", {"name": "rx", "pattern": r"hel+o"})
        results = [s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value for _ in range(10)]
        assert len(set(results)) == 1


class TestJsonKeysScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("json_keys",)

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

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a"]})
        r = s.score(ITEM_JSON, OUT_JSON_STR, CTX)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("json_keys", {"name": "jk", "required": ["a", "x"]})
        results = [s.score(ITEM_JSON, OUT_JSON_STR, CTX).value for _ in range(10)]
        assert len(set(results)) == 1

    def test_m6_error_unknown_param_rejected(self) -> None:
        with pytest.raises(TypeError):
            SCORERS.create("json_keys", {"name": "jk", "not_a_param": 1})


class TestLLMJudgeScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("llm_judge",)

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

    def test_m2_edge_empty_output_and_expected_still_judged(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj"})
        r = s.score(ITEM_EMPTY, OUT_EMPTY, CTX_WITH_JUDGE)
        assert r.value == 0.8  # the judge is still consulted; emptiness is its problem

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX_WITH_JUDGE)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    def test_m5_determinism_with_deterministic_judge(self) -> None:
        s = SCORERS.create("llm_judge", {"name": "lj"})
        results = [s.score(ITEM_NORMAL, OUT_NORMAL, CTX_WITH_JUDGE).value for _ in range(10)]
        assert len(set(results)) == 1


class TestCompositeScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("weighted",)

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

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create(
            "weighted",
            {"name": "comp", "components": [{"type": "exact_match", "weight": 1.0}]},
        )
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.metadata["components"], list)

    def test_m5_determinism(self) -> None:
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
        results = [s.score(ITEM_NORMAL, OUT_NORMAL, CTX).value for _ in range(10)]
        assert len(set(results)) == 1


class TestAutoevalsScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("autoevals",)

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

    def test_m2_edge_empty_output_scores_without_error(self) -> None:
        s = SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})
        r = s.score(ITEM_NORMAL, OUT_EMPTY, CTX)
        assert isinstance(r.value, float)
        assert 0.0 <= r.value <= 1.0

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})
        r = s.score(ITEM_NORMAL, OUT_NORMAL, CTX)
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)
        assert isinstance(r.metadata, dict)

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})
        results = [s.score(ITEM_NORMAL, OUT_MISMATCH, CTX).value for _ in range(10)]
        assert len(set(results)) == 1


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
    def test_m5_determinism_across_argument_key_order(self, name: str) -> None:
        """Two EQUAL trajectories built with different argument key insertion order must
        score identically — plus repeat-scoring stability.

        Re-scoring one object ten times cannot falsify anything: any pure function passes
        it. Dict key order is the property that genuinely varies in-process, so the cell
        scores two separately-built equal trajectories whose argument dicts were
        populated in opposite order. The cross-interpreter/cross-PYTHONHASHSEED
        canonicalisation property stays pinned by real subprocesses in
        tests/test_trajectory_contracts.py.
        """
        params, expected = self._M3_SETUP[name]
        first_args: dict[str, object] = {}
        first_args["x"], first_args["y"] = 1, 2
        second_args: dict[str, object] = {}
        second_args["y"], second_args["x"] = 2, 1
        assert first_args == second_args and list(first_args) != list(second_args)

        def verdict(arguments: dict[str, object]) -> tuple[float, bool | None, str | None]:
            out = traj.output_with(traj.tool_call("a", arguments), traj.final())
            r = _score_trajectory(name, out, expected=expected, params=params)
            return (r.value, r.passed, r.comment)

        assert verdict(first_args) == verdict(second_args)

        stable = traj.output_with(traj.tool_call("a", {"tags": {"x", "y", "z"}}), traj.final())
        repeats = {
            (r.value, r.passed, r.comment)
            for r in (_score_trajectory(name, stable, expected=expected, params=params) for _ in range(10))
        }
        assert len(repeats) == 1

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
        # Explicit ids: the default `params0..params5` cannot say which bad config broke,
        # and three of these cases share a scorer name.
        ids=[
            "step_efficiency-unknown-count-mode",
            "step_efficiency-zero-budget",
            "loop_detection-zero-max-repeats",
            "exact-non-numeric-on-missing",
            "exact-zero-max-depth",
            "exact-unknown-kwarg",
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
    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("inline",)

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
    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("jsonl",)

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

    def test_m3_type_safety(self, tmp_path: Path) -> None:
        p = tmp_path / "data.jsonl"
        p.write_text('{"id":"a","inputs":{"q":"hello"},"expected":"hi"}\n')
        items = list(DATASETS.create("jsonl", {"path": str(p)}).load())
        assert isinstance(items[0], EvalItem)
        assert isinstance(items[0].id, str)

    def test_m6_error_missing_file(self, tmp_path: Path) -> None:
        ds = DATASETS.create("jsonl", {"path": str(tmp_path / "nope.jsonl")})
        with pytest.raises(FileNotFoundError):
            list(ds.load())


class TestCsvDataset:
    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("csv",)

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

    def test_m3_type_safety(self, tmp_path: Path) -> None:
        p = tmp_path / "data.csv"
        p.write_text("id,question,expected\na,hello,hi\n")
        items = list(DATASETS.create("csv", {"path": str(p), "input_columns": ["question"]}).load())
        assert isinstance(items[0], EvalItem)
        assert isinstance(items[0].inputs, dict)

    def test_m6_error_missing_input_column(self, tmp_path: Path) -> None:
        p = tmp_path / "data.csv"
        p.write_text("id,question,expected\na,hello,hi\n")
        ds = DATASETS.create("csv", {"path": str(p), "input_columns": ["nonexistent"]})
        with pytest.raises(ValueError, match="missing required input column"):
            list(ds.load())


# ============================================================================
# TARGETS
# ============================================================================


class TestEchoTarget:
    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("echo",)

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
    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("console",)

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

    def test_m3_type_safety(self, capsys: pytest.CaptureFixture[str]) -> None:
        from eval_harness.sinks import ConsoleSink

        s = SINKS.create("console", {})
        assert isinstance(s, ConsoleSink)
        s.emit(_make_run_result())
        assert s.lines and all(isinstance(line, str) for line in s.lines)
        capsys.readouterr()


class TestJsonFileSink:
    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("json_file",)

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

    def test_m5_determinism_two_emits_byte_identical(self, tmp_path: Path) -> None:
        run = _make_run_result()
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        SINKS.create("json_file", {"path": str(a)}).emit(run)
        SINKS.create("json_file", {"path": str(b)}).emit(run)
        assert a.read_bytes() == b.read_bytes()

    def test_m6_error_unwritable_path_raises(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a directory")
        s = SINKS.create("json_file", {"path": str(blocker / "out.json")})
        with pytest.raises(OSError):
            s.emit(_make_run_result())


class TestHtmlFileSink:
    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("html_file",)

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

    def test_m3_type_safety_render_is_str(self) -> None:
        from eval_harness.sinks import HtmlFileSink

        s = SINKS.create("html_file", {"path": "unused.html"})
        assert isinstance(s, HtmlFileSink)
        rendered = s.render(_make_run_result())
        assert isinstance(rendered, str)
        assert rendered.startswith("<!DOCTYPE html>")

    def test_m5_determinism_two_emits_byte_identical(self, tmp_path: Path) -> None:
        """F-021 promises the report is a pure function of the RunResult."""
        run = _make_run_result()
        a, b = tmp_path / "a.html", tmp_path / "b.html"
        SINKS.create("html_file", {"path": str(a)}).emit(run)
        SINKS.create("html_file", {"path": str(b)}).emit(run)
        assert a.read_bytes() == b.read_bytes()

    def test_m6_error_unwritable_path_raises(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a directory")
        s = SINKS.create("html_file", {"path": str(blocker / "report.html")})
        with pytest.raises(OSError):
            s.emit(_make_run_result())


# ============================================================================
# GATING
# ============================================================================


class TestGating:
    MATRIX_KIND = "gating"

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

    def test_m6_error_unknown_metric_rejected_at_parse(self) -> None:
        """`metric` is a field_validator, not an enum — the rejection surfaces as a
        pydantic.ValidationError through model_validate."""
        import pydantic

        from eval_harness.config.models import GateConfig

        with pytest.raises(pydantic.ValidationError, match="metric"):
            GateConfig.model_validate({"rules": [{"score": "em", "metric": "median", "min": 0.5}]})

    def test_m6_error_neither_bound_set_rejected_at_parse(self) -> None:
        """A rule with neither min nor max is a silent no-op in evaluate_gate() --
        reject it at parse time instead, mirroring the unknown-metric rejection above."""
        import pydantic

        from eval_harness.config.models import GateConfig

        with pytest.raises(pydantic.ValidationError, match="min, max, or both"):
            GateConfig.model_validate({"rules": [{"score": "em", "metric": "mean"}]})

    def test_m6_error_min_exceeds_max_rejected_at_parse(self) -> None:
        """min > max can never be satisfied by any observed value -- reject it at
        parse time rather than let it silently fail every run."""
        import pydantic

        from eval_harness.config.models import GateConfig

        with pytest.raises(pydantic.ValidationError, match="must not exceed max"):
            GateConfig.model_validate({"rules": [{"score": "em", "metric": "mean", "min": 0.9, "max": 0.5}]})

    def test_m6_error_absent_score_fails_the_gate_with_a_reason(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        gate = GateConfig.model_validate({"rules": [{"score": "no_such_score", "metric": "mean", "min": 0.5}]})
        result = evaluate_gate(gate, _make_run_result())
        assert result.passed is False
        assert any("not present" in reason for reason in result.failures)


class TestJudgeCalibrationGating:
    """extend-judge-calibration Group 4: 'gating requires a named calibration
    artifact' (spec.md) — checked against real, constructed ``Scorer`` instances'
    resolved ``.name``/``.uses_judge()``, not guessed from raw config."""

    MATRIX_KIND = "gating"

    @staticmethod
    def _config(**overrides):
        from eval_harness.version import SCHEMA_VERSION

        data = {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo", "params": {}},
        }
        data.update(overrides)
        return EvalConfig.model_validate(data)

    def test_raises_when_a_gate_rule_targets_a_judge_backed_scorer_without_an_artifact(self) -> None:
        from eval_harness.gating import require_calibration_for_judge_gating

        config = self._config(
            judge={"type": "mock", "params": {}},
            gate={"rules": [{"score": "quality", "metric": "mean", "min": 0.5}]},
        )
        scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
        with pytest.raises(ValueError, match="judge_calibration"):
            require_calibration_for_judge_gating(config, scorers)

    def test_passes_when_a_calibration_artifact_is_named(self) -> None:
        from eval_harness.gating import require_calibration_for_judge_gating

        config = self._config(
            judge={"type": "mock", "params": {}},
            judge_calibration={"calibration_artifact_id": "run-123"},
            gate={"rules": [{"score": "quality", "metric": "mean", "min": 0.5}]},
        )
        scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
        require_calibration_for_judge_gating(config, scorers)  # must not raise

    def test_no_artifact_needed_when_the_gate_does_not_target_the_judge_scorer(self) -> None:
        from eval_harness.gating import require_calibration_for_judge_gating

        config = self._config(
            judge={"type": "mock", "params": {}},
            gate={"rules": [{"score": "acc", "metric": "mean", "min": 0.5}]},
        )
        scorers = [
            SCORERS.create("exact_match", {"name": "acc"}),
            SCORERS.create("llm_judge", {"name": "quality"}),
        ]
        require_calibration_for_judge_gating(config, scorers)  # judge isn't gated on -> fine

    def test_no_artifact_needed_when_the_gate_has_no_rules(self) -> None:
        from eval_harness.gating import require_calibration_for_judge_gating

        config = self._config(judge={"type": "mock", "params": {}}, gate={"rules": []})
        scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
        require_calibration_for_judge_gating(config, scorers)  # nothing to gate -> fine

    def test_no_artifact_needed_when_there_is_no_gate_at_all(self) -> None:
        from eval_harness.gating import require_calibration_for_judge_gating

        config = self._config(judge={"type": "mock", "params": {}})
        scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
        require_calibration_for_judge_gating(config, scorers)  # gate is None -> fine


def _repeated_attempts_run(per_item_passed: dict[str, list[bool]]) -> RunResult:
    """A multi-attempt RunResult shaped the way EvalEngine produces one at
    repetitions>1: one ItemResult per (item, attempt), attempt_index set."""
    from datetime import datetime

    items = []
    for item_id, verdicts in per_item_passed.items():
        item = EvalItem(id=item_id, inputs={})
        for idx, passed in enumerate(verdicts):
            items.append(
                ItemResult(
                    item=item,
                    output=TargetOutput(output="x"),
                    scores=[ScoreResult(name="acc", value=1.0 if passed else 0.0, passed=passed)],
                    attempt_index=idx,
                    attempt_id=f"{item_id}:{idx}",
                    item_run_id=f"run:{item_id}",
                )
            )
    return RunResult(
        run_id="reliability-gate-test",
        config_name="test-config",
        items=items,
        aggregate={},
        started_at=datetime(2026, 1, 1, 0, 0, 0),
        finished_at=datetime(2026, 1, 1, 0, 0, 1),
    )


class TestReliabilityGating:
    """`pass_at_k` / `pass_power_k` wired into `evaluate_gate` (F-056)."""

    def test_pass_power_k_gate_passes_when_all_items_all_attempts_pass(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        run = _repeated_attempts_run({"i1": [True, True, True], "i2": [True, True, True]})
        gate = GateConfig.model_validate({"rules": [{"score": "acc", "metric": "pass_power_k", "min": 1.0}]})
        result = evaluate_gate(gate, run)
        assert result.passed is True

    def test_pass_power_k_gate_fails_when_one_item_is_unreliable(self) -> None:
        """A failing reliability gate must exit non-zero — GateResult.passed is
        what `cli.py`'s eval command maps directly to `sys.exit(1)`."""
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        run = _repeated_attempts_run({"i1": [True, True, True], "i2": [True, False, True]})
        gate = GateConfig.model_validate({"rules": [{"score": "acc", "metric": "pass_power_k", "min": 1.0}]})
        result = evaluate_gate(gate, run)
        assert result.passed is False
        assert any("pass_power_k" in reason for reason in result.failures)

    def test_pass_at_k_gate_is_lenient_to_a_single_success(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        run = _repeated_attempts_run({"i1": [False, False, True], "i2": [True, False, False]})
        gate = GateConfig.model_validate({"rules": [{"score": "acc", "metric": "pass_at_k", "min": 1.0}]})
        result = evaluate_gate(gate, run)
        assert result.passed is True  # both items had at least one success

    def test_reliability_rate_reflects_fraction_of_items_not_pooled_attempts(self) -> None:
        """9 easy (all-pass) items + 1 unreliable item (1-of-3): the gate must
        see a 90% pass_power_k rate, not a falsely-inflated pooled number."""
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        per_item = {f"easy{i}": [True, True, True] for i in range(9)}
        per_item["hard"] = [True, False, False]
        run = _repeated_attempts_run(per_item)
        gate = GateConfig.model_validate({"rules": [{"score": "acc", "metric": "pass_power_k", "min": 0.95}]})
        result = evaluate_gate(gate, run)
        assert result.passed is False
        assert any("0.900" in reason for reason in result.failures)

    def test_absent_score_fails_the_gate_with_a_reason(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        run = _repeated_attempts_run({"i1": [True, True]})
        gate = GateConfig.model_validate({"rules": [{"score": "no_such_score", "metric": "pass_power_k", "min": 1.0}]})
        result = evaluate_gate(gate, run)
        assert result.passed is False
        assert any("no_such_score" in reason for reason in result.failures)

    def test_reliability_report_computed_at_most_once_per_gate_call(self) -> None:
        """Two reliability rules in the same gate share one aggregation pass —
        not recomputed per rule."""
        from unittest.mock import patch

        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate
        from eval_harness.reliability import ReliabilityAggregator

        run = _repeated_attempts_run({"i1": [True, True, True]})
        gate = GateConfig.model_validate(
            {
                "rules": [
                    {"score": "acc", "metric": "pass_at_k", "min": 1.0},
                    {"score": "acc", "metric": "pass_power_k", "min": 1.0},
                ]
            }
        )
        with patch.object(ReliabilityAggregator, "aggregate", wraps=ReliabilityAggregator.aggregate) as spy:
            result = evaluate_gate(gate, run)
        assert result.passed is True
        assert spy.call_count == 1


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
            # Exercises the declared judge. Without a judge-backed scorer the judge
            # below is inert config, which is exactly the vacuous credit the execution
            # ledger now refuses.
            {"type": "llm_judge", "params": {"name": "judged"}},
        ],
        "judge": {"type": "mock", "params": {"default_score": 0.95}},
        "sinks": [{"type": "json_file", "params": {"path": "PLACEHOLDER.json"}}],
        "gate": {"rules": [{"score": "em", "metric": "mean", "min": 0.9}]},
    },
    "state_adapter_in_memory": {
        "schema_version": "1.0",
        "run": {"name": "state-adapter-test", "seed": 7},
        "dataset": {
            "type": "inline",
            "params": {"items": [{"id": "s1", "inputs": {"q": "hello"}, "expected": "hello"}]},
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "em"}}],
        "state_adapter": {"type": "in_memory", "params": {}},
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
                        # A judge-backed child alongside programmatic ones: this is the
                        # case CompositeScorer.uses_judge()'s any(...) exists to handle,
                        # and no M8 pipeline exercised it before.
                        {"type": "llm_judge", "weight": 1.0},
                    ],
                },
            }
        ],
        # A distinctive score, not the 1.0 default: with every child at 1.0 the composite
        # mean stays 1.0 whether or not the judge child contributes, so the value
        # assertion could not tell a working judge child from a missing one.
        "judge": {"type": "mock", "params": {"default_score": 0.5}},
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
        # No judge: every trajectory scorer grades tool-call structure deterministically
        # and none reads ctx.judge. Declaring one here credited a judge that never ran.
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
        # No judge, same reasoning as the `trajectory` pipeline above: neither a
        # trajectory scorer nor `contains` is judge-backed.
        "sinks": [{"type": "console"}],
    },
    "repeated_attempts": {
        "schema_version": "1.0",
        "run": {"name": "repeated-attempts-test", "seed": 3, "repetitions": 5, "max_workers": 1},
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {"id": "reliable", "inputs": {"id": "reliable"}, "expected": "correct"},
                    {"id": "flaky", "inputs": {"id": "flaky"}, "expected": "correct"},
                ],
            },
        },
        "target": {"type": "callable", "params": {"path": "tests._sut:reliability_demo"}},
        "scorers": [{"type": "exact_match", "params": {"name": "em"}}],
        "sinks": [],
        "gate": {"rules": [{"score": "em", "metric": "pass_power_k", "min": 1.0}]},
    },
}


#: The engine converts a scorer exception into a failing ScoreResult carrying this
#: prefix (engine.py, `comment=f"scorer error: {exc}"`) rather than raising. That is
#: correct for a genuinely broken scorer, and it is exactly the mechanism that lets a
#: judge which tried and failed to reach the network report a tidy 0.0 instead of a
#: red test. Asserting on the engine's own marker needs no new engine hook.
_SWALLOW_MARKER = "scorer error: "


def _assert_declared_components_ran(name: str, config_dict: dict, ledger: ExecutionLedger) -> None:
    """Fail if this pipeline declared a component whose protocol method never ran.

    Scoped to the single pipeline under test rather than the whole PIPELINES index:
    a component can be legitimately exercised by a sibling pipeline while this one
    only names it, which is exactly the vacuous credit the ledger exists to expose.
    """
    vacuous = pipeline_vacuous({name: config_dict}, {name: ledger.invoked_components()})
    assert not vacuous, f"pipeline {name!r} declares components it never invoked:\n{format_vacuous(vacuous)}"


def _assert_no_swallowed_errors(result: RunResult) -> None:
    """Fail if any score in *result* is a swallowed scorer exception.

    A probed M8 pipeline that "passes" while quietly recording `scorer error: ...`
    has not demonstrated composability -- it has demonstrated the error path.
    """
    for item_result in result.items:
        for score in item_result.scores:
            comment = score.comment or ""
            assert not comment.startswith(_SWALLOW_MARKER), (
                f"item {item_result.item.id!r} scorer {score.name!r} swallowed an exception "
                f"during a probed M8 run: {comment!r}"
            )


@pytest.mark.matrix_offline
class TestM8Composability:
    """M8 - End-to-end engine pipelines over the PIPELINES index.

    Every pipeline runs inside `tests._m8_probe.probe()`, so a component is credited
    for composability only when its protocol method is observed to execute. Before
    that, M8 credited a component for appearing in a validated config dict -- and
    four pipelines were declaring a judge they never invoked.

    `matrix_offline` arms the conftest egress guard for every test below, failing any
    non-loopback `socket.connect`. It is class-level and load-bearing: the guard is
    marker-scoped, so dropping this decorator disarms it silently rather than erroring.
    `tests/test_matrix_coverage_guards.py` asserts the marker is still here, and carries
    the positive control proving the guard fires.
    """

    MATRIX_KIND = "engine"

    def _run(
        self, name: str, tmp_path: Path | None = None
    ) -> tuple[EvalConfig, RunResult, Path | None, ExecutionLedger]:
        config_dict = copy.deepcopy(PIPELINES[name])
        out_path: Path | None = None
        for sink in config_dict.get("sinks", []):
            if sink.get("type") == "json_file":
                assert tmp_path is not None, f"pipeline {name!r} writes a file; pass tmp_path"
                out_path = tmp_path / f"{name}.json"
                sink.setdefault("params", {})["path"] = str(out_path)
        config = EvalConfig.model_validate(config_dict)
        with probe() as ledger:
            result = EvalEngine.from_config(config).run()
        _assert_no_swallowed_errors(result)
        _assert_declared_components_ran(name, config_dict, ledger)
        return config, result, out_path, ledger

    def test_m8_full_pipeline_echo_exact_match(self, tmp_path: Path) -> None:
        """Echo target + exact_match scorer + mock judge + json_file sink."""
        _, result, out_json, _ledger = self._run("echo_exact_match", tmp_path)

        # Verify the pipeline produced correct results
        assert result.config_name == "matrix-test"
        assert len(result.items) == 2
        assert result.aggregate["em"].mean == 1.0
        assert result.aggregate["em"].pass_rate == 1.0
        # contains("hello") matches item m1 but not m2
        assert result.aggregate["c"].mean == 0.5
        # The judge-backed scorer carries the mock judge's configured score, proving the
        # declared judge is genuinely wired through ctx and not merely constructed.
        assert result.aggregate["judged"].mean == 0.95

        # Verify the sink wrote the file
        assert out_json is not None and out_json.exists()
        data = json.loads(out_json.read_text())
        assert data["run_id"] == result.run_id

    def test_m8_pipeline_with_llm_judge_scorer(self) -> None:
        """LLM judge scorer uses injected mock judge through ctx."""
        _, result, _, _ledger = self._run("llm_judge")
        assert result.aggregate["quality"].mean == 0.7

    def test_m8_pipeline_with_composite_scorer(self) -> None:
        """Composite scorer composes children inside the engine pipeline."""
        _, result, _, _ledger = self._run("weighted")
        # (exact_match 1.0 x2 + contains 1.0 x1 + llm_judge 0.5 x1) / 4 == 0.875.
        # Only reachable if the judge-backed child actually ran and was weighted right;
        # with the judge's default 1.0 score this would be 1.0 either way.
        assert result.aggregate["combo"].mean == 0.875

    def test_m8_trajectory_pipeline(self, tmp_path: Path) -> None:
        """All 7 trajectory scorers over the shipped trajectory-emitting callable,
        through config validation, the engine, a file sink and the gate."""
        config, result, out_json, _ledger = self._run("trajectory", tmp_path)

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
        _, result, _, _ledger = self._run("trajectory_mixed")
        assert result.aggregate["trajectory_in_order"].pass_rate == 1.0
        assert result.aggregate["mentions_widget"].pass_rate == 1.0

    def test_m8_repeated_attempts_pipeline(self) -> None:
        """repetitions=5 through a real engine pipeline (F-056): one-of-five
        attempts passes pass@5 and fails pass^5; five-of-five passes both. This
        exercises the attempt loop, ReliabilityAggregator and gating together,
        not each in isolation — and a failing reliability gate fails the run's
        own gate, the same way any other metric does."""
        from eval_harness.reliability import ReliabilityAggregator
        from tests._sut import reset_reliability_demo

        reset_reliability_demo()
        config, result, _, _ledger = self._run("repeated_attempts")

        assert len(result.items) == 10  # 2 items x 5 attempts, every raw attempt persisted

        report = ReliabilityAggregator.aggregate(result.items)
        by_item = {e.item_id: e for e in report.per_item}
        assert by_item["reliable"].pass_at_k is True
        assert by_item["reliable"].pass_power_k is True
        assert by_item["flaky"].success_count == 1
        assert by_item["flaky"].pass_at_k is True
        assert by_item["flaky"].pass_power_k is False

        gate = evaluate_gate(config.gate, result)
        assert gate.passed is False
        assert any("pass_power_k" in f for f in gate.failures)


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
    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("openai",)

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

    def test_m3_type_safety(self) -> None:
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
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)
        assert isinstance(v.reasoning, str)
        assert isinstance(v.raw, dict)


class TestAnthropicJudge:
    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("anthropic",)

    def setup_class(self):
        pytest.importorskip("anthropic")

    @staticmethod
    def _judge_with_response(text: str):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_msg = MagicMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = text
        mock_msg.content = [mock_block]
        mock_client.messages.create.return_value = mock_msg
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            judge = JUDGES.create("anthropic", {"model": MOCK_MODEL_ID_ANTHROPIC, "api_key": MOCK_API_KEY})
        return judge

    def test_m1_correctness(self) -> None:
        j = self._judge_with_response(json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING}))
        v = j.evaluate(MOCK_PROMPT)
        assert v.score == MOCK_SCORE
        assert v.reasoning == MOCK_REASONING

    def test_m2_edge_malformed_response_degrades_to_failure_verdict(self) -> None:
        j = self._judge_with_response("no json here at all")
        v = j.evaluate(MOCK_PROMPT)
        assert v.score == 0.0
        assert "Failed to parse" in v.reasoning

    def test_m3_type_safety(self) -> None:
        j = self._judge_with_response(json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING}))
        v = j.evaluate(MOCK_PROMPT)
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)
        assert isinstance(v.reasoning, str)
        assert isinstance(v.raw, dict)

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
    """Fully mocked via sys.modules injection — no boto3, no skip (the old
    `importorskip("boto3")` kept these cells from ever running in CI, where boto3
    is not installed)."""

    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("bedrock",)

    @staticmethod
    def _judge_with_body(payload: str):
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.invoke_model.return_value = {"body": MagicMock(read=lambda: payload.encode("utf-8"))}
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            judge = JUDGES.create("bedrock", {"model_id": MOCK_MODEL_ID_BEDROCK, "region": MOCK_REGION})
        return judge

    def test_m1_correctness(self) -> None:
        inner_json = json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING})
        j = self._judge_with_body(json.dumps({"content": [{"text": inner_json}]}))
        v = j.evaluate(MOCK_PROMPT)
        assert v.score == MOCK_SCORE
        assert v.reasoning == MOCK_REASONING

    def test_m2_edge_malformed_model_output_raises(self) -> None:
        """Unlike the OpenAI/Anthropic judges there is no degrade-to-0.0 guard here:
        a malformed body raises, and the engine's per-item error handling owns it.
        Pinned so the asymmetry is a recorded contract rather than a surprise."""
        j = self._judge_with_body(json.dumps({"content": [{"text": "not json {{{"}]}))
        with pytest.raises(json.JSONDecodeError):
            j.evaluate(MOCK_PROMPT)

    def test_m3_type_safety(self) -> None:
        inner_json = json.dumps({"score": MOCK_SCORE, "reasoning": MOCK_REASONING})
        j = self._judge_with_body(json.dumps({"content": [{"text": inner_json}]}))
        v = j.evaluate(MOCK_PROMPT)
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)
        assert isinstance(v.raw, dict)

    def test_m6_error_missing_boto3_raises_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "boto3", None)
        with pytest.raises(RuntimeError, match="requires boto3"):
            JUDGES.create("bedrock", {"model_id": MOCK_MODEL_ID_BEDROCK, "region": MOCK_REGION})


class TestPhoenixEvalJudge:
    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("phoenix_evals",)

    @staticmethod
    def _judge_with_evaluator(mock_evaluator: MagicMock):
        mock_px = MagicMock()
        mock_px.LLM = MagicMock()
        mock_px.ClassificationEvaluator = MagicMock(return_value=mock_evaluator)
        with patch.dict("sys.modules", {"phoenix.evals": mock_px}):
            judge = JUDGES.create("phoenix_evals", {"model": MOCK_MODEL_ID_OPENAI})
        return judge

    def test_m1_correctness(self) -> None:
        mock_evaluator = MagicMock()
        mock_result = MagicMock()
        mock_result.label = "pass"
        mock_result.score = 1.0
        mock_result.explanation = "pass"
        mock_evaluator.evaluate.return_value = [mock_result]

        j = self._judge_with_evaluator(mock_evaluator)
        v = j.evaluate("some prompt")
        assert v.score == 1.0
        assert v.reasoning == "pass"

    def test_m2_edge_evaluator_failure_degrades_to_failure_verdict(self) -> None:
        """A judge outage must not crash the run: fail-safe 0.0 verdict with the cause."""
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate.side_effect = RuntimeError("provider down")
        j = self._judge_with_evaluator(mock_evaluator)
        v = j.evaluate("some prompt")
        assert v.score == 0.0
        assert "phoenix-evals failed" in v.reasoning

    def test_m3_type_safety(self) -> None:
        mock_evaluator = MagicMock()
        mock_result = MagicMock()
        mock_result.label = "fail"
        mock_result.score = None
        mock_result.explanation = ""
        mock_evaluator.evaluate.return_value = [mock_result]

        j = self._judge_with_evaluator(mock_evaluator)
        v = j.evaluate("some prompt")
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)  # label-mapped, not None
        assert isinstance(v.raw, dict)

    def test_m6_error_missing_sdk_raises_install_hint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "phoenix.evals", None)
        with pytest.raises(RuntimeError, match="requires arize-phoenix-evals"):
            JUDGES.create("phoenix_evals", {"model": MOCK_MODEL_ID_OPENAI})


# ----------------------------------------------------------------------------
# 2. DATASETS
# ----------------------------------------------------------------------------


def _write_parquet(path: Path, columns: dict[str, list]) -> Path:
    """Write a Parquet fixture with pyarrow only — no pandas.

    `ParquetDataset.load()` imports `pyarrow.parquet` and nothing else, and pyarrow is
    the whole of the `parquet` extra (`pyproject.toml`) and is also in `dev`. pandas is
    in NEITHER, and CI installs `.[dev,langfuse,openai,parquet,autoevals]` — so the
    earlier `importorskip("pandas")` on this class skipped every parquet cell in CI
    while the coverage artifact claimed them: a false green of exactly the class this
    feature exists to eliminate. Building the fixture on the SUT's own dependency makes
    these cells execute where they are claimed.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table(columns), str(path))
    return path


class TestParquetDataset:
    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("parquet",)

    def setup_class(self):
        pytest.importorskip("pyarrow", reason="pyarrow is the parquet extra and is in dev; pandas is not needed")

    def test_m1_correctness(self, tmp_path: Path) -> None:
        p = _write_parquet(
            tmp_path / "test_data.parquet",
            {"id": ["ds-1"], "question": ["q1"], "expected": ["a1"]},
        )
        ds = DATASETS.create("parquet", {"path": p.as_posix(), "input_columns": ["question"]})
        items = list(ds.load())
        assert len(items) == 1
        assert items[0].id == "ds-1"
        assert items[0].inputs == {"question": "q1"}
        assert items[0].expected == "a1"

    def test_m2_edge_empty_table_yields_no_items(self, tmp_path: Path) -> None:
        p = _write_parquet(tmp_path / "empty.parquet", {"id": [], "question": [], "expected": []})
        ds = DATASETS.create("parquet", {"path": p.as_posix(), "input_columns": ["question"]})
        assert list(ds.load()) == []

    def test_m3_type_safety(self, tmp_path: Path) -> None:
        p = _write_parquet(
            tmp_path / "typed.parquet",
            {"id": [42], "question": ["q1"], "expected": ["a1"]},
        )
        items = list(DATASETS.create("parquet", {"path": p.as_posix(), "input_columns": ["question"]}).load())
        assert isinstance(items[0], EvalItem)
        # A non-string id column is coerced to str, so downstream item ids stay uniform.
        assert items[0].id == "42"
        assert isinstance(items[0].metadata, dict)

    def test_m6_missing_file(self) -> None:
        ds = DATASETS.create("parquet", {"path": "invalid-path-123.parquet"})
        with pytest.raises(FileNotFoundError):
            list(ds.load())

    def test_m6_error_missing_input_column(self, tmp_path: Path) -> None:
        p = _write_parquet(tmp_path / "cols.parquet", {"id": ["a"], "question": ["q"]})
        ds = DATASETS.create("parquet", {"path": p.as_posix(), "input_columns": ["nonexistent"]})
        with pytest.raises(ValueError, match="missing required input column"):
            list(ds.load())


class TestLangfuseDataset:
    """Fully mocked via the attach_client seam — no SDK, no skip (AGENTS.md offline-DI)."""

    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("langfuse",)

    def test_m1_correctness(self) -> None:
        mock_client = MagicMock()
        mock_item = {"id": "lf-1", "inputs": {"q": "test"}, "expected": "ans"}
        mock_client.get_dataset_items.return_value = [mock_item]

        ds = DATASETS.create("langfuse", {"dataset_name": "test-langfuse-ds"})
        ds.attach_client(mock_client)  # type: ignore[attr-defined]
        items = list(ds.load())
        assert len(items) == 1
        assert items[0].id == "lf-1"

    def test_m2_edge_empty_remote_dataset(self) -> None:
        mock_client = MagicMock()
        mock_client.get_dataset_items.return_value = []
        ds = DATASETS.create("langfuse", {"dataset_name": "empty-ds"})
        ds.attach_client(mock_client)  # type: ignore[attr-defined]
        assert list(ds.load()) == []

    def test_m3_type_safety(self) -> None:
        mock_client = MagicMock()
        mock_client.get_dataset_items.return_value = [{"id": None, "inputs": {"q": "x"}}]
        ds = DATASETS.create("langfuse", {"dataset_name": "typed-ds"})
        ds.attach_client(mock_client)  # type: ignore[attr-defined]
        items = list(ds.load())
        assert isinstance(items[0], EvalItem)
        # A present-but-None id falls back to the positional index, not the string "None".
        assert items[0].id == "0"

    def test_m6_error_load_without_client(self) -> None:
        ds = DATASETS.create("langfuse", {"dataset_name": "no-client-ds"})
        with pytest.raises(RuntimeError, match="no client attached"):
            list(ds.load())


class TestBraintrustDataset:
    """Fully mocked (sys.modules injection / the fetch seam) — no SDK, no skip.

    The pre-matrix version of this class sat under `importorskip("braintrust")` — a
    package deliberately absent from CI — and its one test omitted the required
    `project_name` argument: a matrix cell that could never run and never passed.
    """

    MATRIX_KIND = "dataset"
    MATRIX_COMPONENTS = ("braintrust",)

    def test_m1_correctness(self) -> None:
        mock_bt = MagicMock()
        mock_ds = MagicMock()
        mock_bt.init_dataset.return_value = mock_ds
        mock_ds.__iter__.return_value = [{"id": "bt-1", "input": {"q": "test"}, "expected": "ans"}]

        with patch.dict("sys.modules", {"braintrust": mock_bt}):
            ds = DATASETS.create("braintrust", {"project_name": "proj", "name": "test-braintrust-ds"})
            items = list(ds.load())
            assert len(items) == 1
            assert items[0].id == "bt-1"

    def test_m2_edge_empty_remote_dataset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("eval_harness.datasets.fetch_dataset_items", lambda **kw: [])
        ds = DATASETS.create("braintrust", {"project_name": "proj", "name": "empty-ds"})
        assert list(ds.load()) == []

    def test_m3_type_safety(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "eval_harness.datasets.fetch_dataset_items",
            lambda **kw: [{"id": "bt-1", "inputs": {"q": "x"}, "expected": "y"}],
        )
        items = list(DATASETS.create("braintrust", {"project_name": "proj", "name": "typed-ds"}).load())
        assert isinstance(items[0], EvalItem)
        assert isinstance(items[0].id, str)

    def test_m6_error_sdk_absent_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dataset must not silently degrade to an empty eval when the SDK is missing."""
        monkeypatch.setitem(sys.modules, "braintrust", None)
        ds = DATASETS.create("braintrust", {"project_name": "proj", "name": "no-sdk-ds"})
        with pytest.raises(RuntimeError, match="braintrust"):
            list(ds.load())


# ----------------------------------------------------------------------------
# 3. TARGETS
# ----------------------------------------------------------------------------


class TestCallableTarget:
    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("callable",)

    def test_m1_correctness(self) -> None:
        t = TARGETS.create("callable", {"path": "json:dumps"})
        out = t.run(ITEM_NORMAL)
        assert out.output is not None
        assert isinstance(out.output, str)

    def test_m2_edge_sut_exception_becomes_scored_error(self) -> None:
        """A raising SUT is captured as TargetOutput.error, never a raised exception."""
        t = TARGETS.create("callable", {"path": "tests._sut:boom"})
        out = t.run(ITEM_NORMAL)
        assert out.output is None
        assert out.error is not None and "kaboom" in out.error

    def test_m3_type_safety_targetoutput_passthrough(self) -> None:
        """The F-051 seam: a callable returning its own TargetOutput passes through
        unchanged (trajectory kept; a pre-measured latency is not overwritten)."""
        t = TARGETS.create("callable", {"path": "tests._sut:preset_latency_output"})
        out = t.run(ITEM_NORMAL)
        assert isinstance(out, TargetOutput)
        assert out.latency_ms == 123.5

        t2 = TARGETS.create("callable", {"path": "tests._sut:trajectory_demo"})
        out2 = t2.run(EvalItem(id="t", inputs={"question": "q"}))
        assert out2.trajectory is not None

    def test_m6_error(self) -> None:
        t = TARGETS.create("callable", {"path": "nonexistent.module_xyz:func_abc"})
        with pytest.raises(ImportError):
            t.run(ITEM_NORMAL)


class TestModelTarget:
    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("model",)

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

    def test_m2_edge_empty_stream_yields_empty_output(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = []
        t = TARGETS.create(
            "model",
            {"model": MOCK_MODEL_ID_OPENAI, "provider": "openai", "client": mock_client, "prompt_template": "{q}"},
        )
        out = t.run(ITEM_NORMAL)
        assert out.output == ""
        assert out.error is None

    def test_m3_type_safety(self) -> None:
        mock_client = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "typed"
        mock_client.chat.completions.create.return_value = [mock_chunk]
        t = TARGETS.create(
            "model",
            {"model": MOCK_MODEL_ID_OPENAI, "provider": "openai", "client": mock_client, "prompt_template": "{q}"},
        )
        out = t.run(ITEM_NORMAL)
        assert isinstance(out, TargetOutput)
        assert isinstance(out.latency_ms, float)
        assert out.metadata == {"provider": "openai", "model": MOCK_MODEL_ID_OPENAI}

    def test_m6_error_unknown_provider_rejected(self) -> None:
        with pytest.raises(ValueError, match="provider must be one of"):
            TARGETS.create("model", {"model": MOCK_MODEL_ID_OPENAI, "provider": "bogus"})

    def test_m6_error_transport_failure_becomes_scored_error(self) -> None:
        """The riskiest surface in the kind: a live-API failure is captured as
        TargetOutput.error, never an exception out of run()."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = ConnectionError("socket closed")
        t = TARGETS.create(
            "model",
            {"model": MOCK_MODEL_ID_OPENAI, "provider": "openai", "client": mock_client, "prompt_template": "{q}"},
        )
        out = t.run(ITEM_NORMAL)
        assert out.output is None
        assert out.error is not None and "socket closed" in out.error


# ----------------------------------------------------------------------------
# 4. SINKS
# ----------------------------------------------------------------------------


class TestLangfuseSink:
    """Fully mocked via the attach_client seam — no SDK, no skip."""

    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("langfuse",)

    def test_m1_correctness_and_m5_lifecycle(self) -> None:
        mock_client = MagicMock()
        s = SINKS.create("langfuse", {})
        s.attach_client(mock_client)  # type: ignore[attr-defined]
        s.emit(_make_run_result())
        mock_client.log_score.assert_called()
        mock_client.flush.assert_called()

    def test_m6_error_emit_without_client_fails_closed(self) -> None:
        s = SINKS.create("langfuse", {})
        with pytest.raises(RuntimeError, match="no client attached"):
            s.emit(_make_run_result())


class TestPhoenixSink:
    """Asserts through the recording null client rather than "it did not crash".

    `NullPhoenixScoreClient` documents itself as a test double that records calls, and
    the earlier version of this class asserted nothing at all — a no-op `emit` and a
    `build_score_client` that never degraded both passed it, while the coverage artifact
    reported the component's whole floor as covered.
    """

    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("phoenix",)

    def test_m1_correctness_disabled_default_logs_every_score(self) -> None:
        from eval_harness.phoenix_client import NullPhoenixScoreClient

        s = SINKS.create("phoenix", {})
        s.emit(_make_run_result())
        client = s._client  # type: ignore[attr-defined]
        assert isinstance(client, NullPhoenixScoreClient)
        assert [row["name"] for row in client.scores] == ["exact_match"]
        assert client.scores[0]["item_id"] == "t1"
        assert client.scores[0]["value"] == 1.0
        assert client.flushed is True

    def test_m1_correctness_min_value_filters_scores(self) -> None:
        s = SINKS.create("phoenix", {"min_value_to_log": 2.0})
        s.emit(_make_run_result())
        assert s._client.scores == []  # type: ignore[attr-defined]
        assert s._client.flushed is True  # type: ignore[attr-defined]

    def test_m6_error_enabled_without_sdk_degrades_to_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Export requested but the OTel SDK is absent: degrade to the null client and
        still complete the run. The degrade IS the contract, so it is what's asserted."""
        import eval_harness.phoenix_client as phoenix_client
        from eval_harness.phoenix_client import NullPhoenixScoreClient

        monkeypatch.setattr(phoenix_client, "_otel_tracer", lambda: None)
        s = SINKS.create("phoenix", {"enabled": True})
        assert isinstance(s._client, NullPhoenixScoreClient)  # type: ignore[attr-defined]
        s.emit(_make_run_result())
        assert s._client.flushed is True  # type: ignore[attr-defined]


class TestBraintrustSink:
    """Fully mocked (sys.modules injection) — no SDK, no skip.

    The pre-matrix version of this class sat under `importorskip("braintrust")` and its
    one test could never have passed: it asserted a flush on `init_logger` (a function
    the sink never calls) and invoked a `close()` method the sink does not have —
    another cell that never ran anywhere.
    """

    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("braintrust",)

    def test_m1_correctness_logs_each_item_and_flushes(self) -> None:
        mock_bt = MagicMock()
        mock_experiment = MagicMock()
        mock_bt.init.return_value = mock_experiment
        with patch.dict("sys.modules", {"braintrust": mock_bt}):
            s = SINKS.create("braintrust", {"enabled": True})
            s.emit(_make_run_result())
        mock_bt.init.assert_called_once_with(project="eval-harness", experiment="test-run-001")
        mock_experiment.log.assert_called_once()
        mock_experiment.flush.assert_called_once()

    def test_m6_error_enabled_without_sdk_degrades_to_no_op(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Telemetry must not break the run — and the degrade path is asserted, not
        merely survived: the null client is chosen AND the items still round-trip it."""
        from eval_harness.braintrust_client import NullBrainTrustClient

        monkeypatch.setitem(sys.modules, "braintrust", None)
        s = SINKS.create("braintrust", {"enabled": True})
        s.emit(_make_run_result())
        client = s._client  # type: ignore[attr-defined]
        assert isinstance(client, NullBrainTrustClient)
        assert [row["item_id"] for row in client.items] == ["t1"]
        assert client.items[0]["scores"] == {"exact_match": 1.0}
        assert client.flushed is True


class TestSinksShared:
    """Cross-sink edge: emitting a zero-item run must not crash any sink."""

    MATRIX_KIND = "sink"
    MATRIX_COMPONENTS = ("console", "json_file", "html_file", "langfuse", "phoenix", "braintrust")

    @pytest.mark.parametrize("name", MATRIX_COMPONENTS)
    def test_m2_edge_empty_run_emits_an_empty_but_valid_artifact(self, name: str, tmp_path: Path) -> None:
        """Every sink must survive a zero-item run AND produce the empty artifact, not
        merely avoid raising: "did not crash" would pass a sink whose emit() was gutted.
        """
        from datetime import datetime

        empty = RunResult(
            run_id="empty-run",
            config_name="empty",
            items=[],
            aggregate={},
            started_at=datetime(2026, 1, 1, 0, 0, 0),
            finished_at=datetime(2026, 1, 1, 0, 0, 1),
        )
        params: dict = {}
        out_path: Path | None = None
        if name in ("json_file", "html_file"):
            out_path = tmp_path / f"{name}.out"
            params["path"] = str(out_path)
        sink = SINKS.create(name, params)
        client: MagicMock | None = None
        if name == "langfuse":
            client = MagicMock()
            sink.attach_client(client)  # type: ignore[attr-defined]

        sink.emit(empty)

        if name == "json_file":
            assert out_path is not None
            payload = json.loads(out_path.read_text())
            assert payload["run_id"] == "empty-run"
            assert payload["items"] == []
        elif name == "html_file":
            assert out_path is not None
            rendered = out_path.read_text()
            assert "empty-run" in rendered and rendered.rstrip().endswith("</html>")
        elif name == "console":
            assert sink.lines == ["run 'empty-run' — 0 item(s)"]  # type: ignore[attr-defined]
        elif name == "langfuse":
            assert client is not None
            client.log_score.assert_not_called()  # nothing to score
            client.flush.assert_called_once()  # but the client is still closed out
        else:  # phoenix / braintrust self-construct a recording null client
            recorded = getattr(sink._client, "scores", None)  # type: ignore[attr-defined]
            if recorded is None:
                recorded = sink._client.items  # type: ignore[attr-defined]
            assert recorded == []
            assert sink._client.flushed is True  # type: ignore[attr-defined]
