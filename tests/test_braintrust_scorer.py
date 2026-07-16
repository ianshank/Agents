"""autoevals scorer bridge — offline tests.

The bridge is exercised against the real ``autoevals`` package (a lightweight, offline-safe
dependency installed in the test job). Only the pure-Python **Heuristic** scorers are used
here (``Levenshtein``); LLM/Embedding scorers are covered by opt-in live tests. Skip/error
handling and the missing-package fallback are tested with fakes so no network or model is
touched.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from eval_harness.core.types import EvalItem, RunContext, TargetOutput
from eval_harness.plugins import SCORERS
from eval_harness.scorers import AutoevalsScorer


def _autoevals(params: dict[str, object]) -> AutoevalsScorer:
    scorer = SCORERS.create("autoevals", params)
    assert isinstance(scorer, AutoevalsScorer)
    return scorer


def _score(scorer: AutoevalsScorer, output: object, expected: object, inputs: dict | None = None):
    item = EvalItem(id="1", inputs=inputs or {}, expected=expected)
    return scorer.score(item, TargetOutput(output=output), RunContext(config={}))


# -- real Levenshtein (offline-safe heuristic) -------------------------------


def test_autoevals_levenshtein_scores_offline() -> None:
    res = _score(_autoevals({"scorer": "Levenshtein"}), "kitten", "sitting")
    assert res.name == "Levenshtein"
    assert 0.0 < res.value < 1.0
    assert res.passed is not None


def test_autoevals_name_defaults_to_scorer() -> None:
    assert _autoevals({"scorer": "Levenshtein"}).name == "Levenshtein"


def test_autoevals_custom_name_wins() -> None:
    assert _autoevals({"scorer": "Levenshtein", "name": "edit_distance"}).name == "edit_distance"


def test_autoevals_perfect_match_passes() -> None:
    res = _score(_autoevals({"scorer": "Levenshtein"}), "same", "same")
    assert res.value == 1.0
    assert res.passed is True


def test_autoevals_threshold_controls_passed() -> None:
    res = _score(_autoevals({"scorer": "Levenshtein", "threshold": 0.99}), "kitten", "sitting")
    assert res.passed is False  # ~0.57 < 0.99


# -- construction errors -----------------------------------------------------


def test_autoevals_unknown_scorer_raises() -> None:
    with pytest.raises(ValueError, match="unknown autoevals scorer"):
        _autoevals({"scorer": "NoSuchScorer"})


def test_autoevals_missing_package_raises(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "autoevals", None)  # force ImportError on lazy import
    with pytest.raises(RuntimeError, match="autoevals"):
        _autoevals({"scorer": "Levenshtein"})


# -- runtime fallbacks (fake evaluator) --------------------------------------


def test_autoevals_failsafe_on_evaluator_error() -> None:
    scorer = _autoevals({"scorer": "Levenshtein"})

    def _boom(**_kwargs):
        raise RuntimeError("provider down")

    scorer._evaluator = _boom  # type: ignore[assignment]
    res = _score(scorer, "a", "b")
    assert res.value == 0.0
    assert res.passed is False
    assert res.comment is not None and res.comment.startswith("autoevals error")


def test_autoevals_skip_none_maps_to_on_skip() -> None:
    scorer = _autoevals({"scorer": "Levenshtein"})
    scorer._evaluator = lambda **k: SimpleNamespace(score=None, metadata={})  # type: ignore[assignment]
    res = _score(scorer, "a", "b")
    assert res.value == 0.0  # default on_skip
    assert res.passed is None
    assert res.comment == "autoevals skipped (score=None)"


def test_autoevals_on_skip_override() -> None:
    scorer = _autoevals({"scorer": "Levenshtein", "on_skip": 0.5})
    scorer._evaluator = lambda **k: SimpleNamespace(score=None, metadata={})  # type: ignore[assignment]
    assert _score(scorer, "a", "b").value == 0.5


def test_autoevals_coerce_text_stringifies_inputs() -> None:
    scorer = _autoevals({"scorer": "Levenshtein", "coerce_text": True})
    seen: dict = {}

    def _recorder(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(score=1.0, metadata={})

    scorer._evaluator = _recorder  # type: ignore[assignment]
    item = EvalItem(id="1", inputs={"a": 1}, expected=None)
    scorer.score(item, TargetOutput(output=123), RunContext(config={}))
    assert seen["output"] == "123"  # non-string output coerced to text
    assert seen["expected"] is None  # None left as-is
    assert isinstance(seen["input"], str)  # dict input coerced to text


def test_autoevals_rationale_becomes_comment() -> None:
    scorer = _autoevals({"scorer": "Levenshtein"})
    scorer._evaluator = lambda **k: SimpleNamespace(score=0.8, metadata={"rationale": "close enough"})  # type: ignore[assignment]
    res = _score(scorer, "a", "b")
    assert res.value == 0.8
    assert res.passed is True
    assert res.comment == "close enough"
    assert res.metadata == {"rationale": "close enough"}
