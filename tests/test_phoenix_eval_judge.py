"""PhoenixEvalJudge — arize-phoenix-evals LLM-as-a-judge, offline tests.

The real ``phoenix.evals`` package is not installable in the air-gapped suite, so
the SDK path is exercised via ``sys.modules`` injection. The offline tests prove the
verdict-mapping + fail-safe logic and the "SDK missing → clear install error" path;
the *live* correctness of the arize-phoenix-evals 0.29 API call is validated on a
networked runner (see docs/phoenix-spike.md).
"""

from __future__ import annotations

import sys
import types

import pytest

from eval_harness.core.types import JudgeVerdict
from eval_harness.plugins import JUDGES


class _Result:
    def __init__(self, label, score, explanation):
        self.label = label
        self.score = score
        self.explanation = explanation


class _FakeEvaluator:
    def __init__(self, result, raises=False):
        self._result = result
        self._raises = raises
        self.last_input: dict | None = None

    def evaluate(self, eval_input):
        self.last_input = eval_input
        if self._raises:
            raise RuntimeError("phoenix-evals boom")
        return [self._result]


def _install_fake_phoenix_evals(monkeypatch, evaluator) -> None:
    """Make ``from phoenix.evals import LLM, ClassificationEvaluator`` resolve offline."""
    evals = types.ModuleType("phoenix.evals")

    class _LLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    evals.LLM = _LLM  # type: ignore[attr-defined]
    evals.ClassificationEvaluator = lambda **kwargs: evaluator  # type: ignore[attr-defined]
    phoenix = types.ModuleType("phoenix")
    phoenix.evals = evals  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "phoenix", phoenix)
    monkeypatch.setitem(sys.modules, "phoenix.evals", evals)


def _judge(model="m", **params):
    from eval_harness.judges import PhoenixEvalJudge

    return PhoenixEvalJudge(model=model, **params)


def test_phoenix_eval_judge_is_registered() -> None:
    assert "phoenix_evals" in JUDGES.names()


def test_construct_without_sdk_raises_clear_install_error() -> None:
    from eval_harness.judges import PhoenixEvalJudge

    with pytest.raises(RuntimeError, match="phoenix-evals"):
        PhoenixEvalJudge(model="m")  # arize-phoenix-evals genuinely absent here


def test_evaluate_maps_label_score_explanation_to_verdict(monkeypatch) -> None:
    _install_fake_phoenix_evals(monkeypatch, _FakeEvaluator(_Result("pass", 1.0, "looks good")))
    verdict = _judge().evaluate("is this correct?", {"output": "42"})
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.score == 1.0
    assert verdict.reasoning == "looks good"
    assert verdict.raw["label"] == "pass"


def test_evaluate_falls_back_to_choices_when_score_is_none(monkeypatch) -> None:
    _install_fake_phoenix_evals(monkeypatch, _FakeEvaluator(_Result("fail", None, "")))
    verdict = _judge(choices={"pass": 1.0, "fail": 0.0}).evaluate("q")
    assert verdict.score == 0.0  # score None → mapped from the label via choices


def test_evaluate_is_failsafe(monkeypatch) -> None:
    _install_fake_phoenix_evals(monkeypatch, _FakeEvaluator(None, raises=True))
    verdict = _judge().evaluate("q")
    assert verdict.score == 0.0
    assert "phoenix" in verdict.reasoning.lower()


def test_evaluate_forwards_prompt_and_context_as_eval_input(monkeypatch) -> None:
    ev = _FakeEvaluator(_Result("pass", 1.0, "ok"))
    _install_fake_phoenix_evals(monkeypatch, ev)
    _judge().evaluate("the-prompt", {"output": "x"})
    assert ev.last_input == {"prompt": "the-prompt", "output": "x"}


def test_evaluate_defaults_to_zero_when_label_and_score_missing(monkeypatch) -> None:
    _install_fake_phoenix_evals(monkeypatch, _FakeEvaluator(_Result(None, None, "")))
    verdict = _judge().evaluate("q")
    assert verdict.score == 0.0  # neither score nor a mappable label → safe default
