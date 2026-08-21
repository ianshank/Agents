from __future__ import annotations

import pytest

from eval_harness.core.types import EvalItem, RunContext, TargetOutput
from eval_harness.judges import MockJudge
from eval_harness.plugins import SCORERS


def _ctx(judge=None):
    return RunContext(config=None, judge=judge)


def _item(expected=None, **inputs):
    return EvalItem(id="i", inputs=inputs, expected=expected)


def test_exact_match():
    s = SCORERS.create("exact_match", {"case_sensitive": False})
    r = s.score(_item(expected="Hello"), TargetOutput(output="hello"), _ctx())
    assert r.value == 1.0 and r.passed


def test_exact_match_mismatch():
    s = SCORERS.create("exact", {})  # alias
    r = s.score(_item(expected="a"), TargetOutput(output="b"), _ctx())
    assert r.value == 0.0 and r.passed is False


def test_regex():
    s = SCORERS.create("regex", {"pattern": r"\d{3}"})
    assert s.score(_item(), TargetOutput(output="abc123"), _ctx()).passed
    assert not s.score(_item(), TargetOutput(output="abc"), _ctx()).passed


def test_contains():
    s = SCORERS.create("contains", {"substring": "Reset"})
    assert s.score(_item(), TargetOutput(output="please reset now"), _ctx()).passed


def test_json_keys_partial():
    s = SCORERS.create("json_keys", {"required": ["a", "b"]})
    r = s.score(_item(), TargetOutput(output={"a": 1}), _ctx())
    assert r.value == 0.5 and r.passed is False
    assert "missing keys" in r.comment


def test_json_keys_from_string():
    s = SCORERS.create("json_keys", {"required": ["a"]})
    r = s.score(_item(), TargetOutput(output='{"a": 1}'), _ctx())
    assert r.value == 1.0 and r.passed


def test_json_keys_invalid_json():
    s = SCORERS.create("json_keys", {"required": ["a"]})
    r = s.score(_item(), TargetOutput(output="not json"), _ctx())
    assert r.value == 0.0 and r.passed is False


def test_llm_judge_uses_injected_judge():
    s = SCORERS.create("llm_judge", {"threshold": 0.7})
    judge = MockJudge(default_score=0.9)
    r = s.score(_item(expected="x"), TargetOutput(output="y"), _ctx(judge))
    assert r.value == 0.9 and r.passed


def test_llm_judge_requires_judge():
    s = SCORERS.create("llm_judge", {})
    with pytest.raises(RuntimeError):
        s.score(_item(), TargetOutput(output="y"), _ctx(None))


def test_llm_judge_scorer_treats_abstained_verdict_as_passed_none():
    from eval_harness.core.interfaces import Judge
    from eval_harness.core.types import JudgeVerdict

    class _AbstainingJudge(Judge):
        def evaluate(self, prompt, context=None):
            return JudgeVerdict(score=0.0, reasoning="below quorum", raw={"abstained": True})

    # threshold=0.0: score 0.0 would otherwise satisfy `score >= threshold` and pass --
    # proves the abstained branch actually overrides the threshold comparison, not just
    # coincides with a failing one.
    s = SCORERS.create("llm_judge", {"threshold": 0.0})
    r = s.score(_item(expected="x"), TargetOutput(output="y"), _ctx(_AbstainingJudge()))
    assert r.passed is None
    assert r.value == 0.0
