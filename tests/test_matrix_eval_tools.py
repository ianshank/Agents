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

import json
import re
from pathlib import Path

import pytest

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
from eval_harness.plugins import DATASETS, JUDGES, SCORERS, SINKS, TARGETS, bootstrap

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
        import sys
        monkeypatch.setitem(sys.modules, "autoevals", None)
        with pytest.raises(RuntimeError, match="The 'autoevals' package is required"):
            SCORERS.create("autoevals", {"name": "ae", "scorer": "Levenshtein"})


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

        gate = GateConfig(rules=[{"score": "exact_match", "metric": "mean", "min": 0.5}])
        run = _make_run_result()
        result = evaluate_gate(gate, run)
        assert result.passed is True

    def test_m1_correctness_gate_fail(self) -> None:
        from eval_harness.config.models import GateConfig
        from eval_harness.gating import evaluate_gate

        gate = GateConfig(rules=[{"score": "exact_match", "metric": "mean", "min": 1.5}])
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


class TestM8Composability:
    """M8 - End-to-end engine pipeline with real components."""

    def test_full_pipeline_echo_exact_match(self, tmp_path: Path) -> None:
        """Echo target + exact_match scorer + mock judge + json_file sink."""
        from eval_harness.config import EvalConfig

        out_json = tmp_path / "out.json"
        config_dict = {
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
            "sinks": [{"type": "json_file", "params": {"path": str(out_json)}}],
            "gate": {"rules": [{"score": "em", "metric": "mean", "min": 0.9}]},
        }
        config = EvalConfig(**config_dict)
        from eval_harness.engine import EvalEngine

        engine = EvalEngine.from_config(config)
        result = engine.run()

        # Verify the pipeline produced correct results
        assert result.config_name == "matrix-test"
        assert len(result.items) == 2
        assert result.aggregate["em"].mean == 1.0
        assert result.aggregate["em"].pass_rate == 1.0
        # contains("hello") matches item m1 but not m2
        assert result.aggregate["c"].mean == 0.5

        # Verify the sink wrote the file
        assert out_json.exists()
        data = json.loads(out_json.read_text())
        assert data["run_id"] == result.run_id

    def test_pipeline_with_llm_judge_scorer(self) -> None:
        """LLM judge scorer uses injected mock judge through ctx."""
        from eval_harness.config import EvalConfig
        from eval_harness.engine import EvalEngine

        config = EvalConfig(
            **{
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
            }
        )
        result = EvalEngine.from_config(config).run()
        assert result.aggregate["quality"].mean == 0.7

    def test_pipeline_with_composite_scorer(self) -> None:
        """Composite scorer composes children inside the engine pipeline."""
        from eval_harness.config import EvalConfig
        from eval_harness.engine import EvalEngine

        config = EvalConfig(
            **{
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
            }
        )
        result = EvalEngine.from_config(config).run()
        assert result.aggregate["combo"].mean == 1.0
