"""LLM-as-a-judge via arize-phoenix-evals' ``ClassificationEvaluator``."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

logger = logging.getLogger(__name__)


@JUDGES.register("phoenix_evals", aliases=("phoenix-evals",))
class PhoenixEvalJudge(Judge):
    """LLM-as-a-judge via arize-phoenix-evals' ``ClassificationEvaluator``.

    A pluggable alternative to the OpenAI/Anthropic judges that reuses Phoenix's
    pre-built evaluator machinery. ``arize-phoenix-evals`` is imported lazily (kept
    out of ``dev``); construction raises a clear install error when it is absent.
    Provider credentials are the SDK's own env vars — nothing is hardcoded here.

    The SDK surface targets arize-phoenix-evals 0.29 (``LLM`` + ``ClassificationEvaluator``);
    validate against the installed version on a networked runner before relying on it.
    """

    #: Default label→score map when the caller doesn't supply one.
    _DEFAULT_CHOICES: ClassVar[dict[str, float]] = {"pass": 1.0, "fail": 0.0}

    def __init__(
        self,
        model: str,
        *,
        provider: str = "openai",
        name: str = "phoenix_eval",
        prompt_template: str = "{prompt}",
        choices: dict[str, float] | None = None,
    ):
        try:
            from phoenix.evals import LLM, ClassificationEvaluator
        except ImportError as exc:
            raise RuntimeError(
                "PhoenixEvalJudge requires arize-phoenix-evals. "
                "Install with: pip install 'langfuse-eval-harness[phoenix-evals]'"
            ) from exc
        self._choices = dict(choices) if choices else dict(self._DEFAULT_CHOICES)
        llm = LLM(provider=provider, model=model)
        self._evaluator = ClassificationEvaluator(
            name=name, llm=llm, prompt_template=prompt_template, choices=self._choices
        )

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        eval_input: dict[str, Any] = {"prompt": prompt}
        if context:
            eval_input.update(context)
        try:
            result = self._evaluator.evaluate(eval_input=eval_input)[0]
        except Exception as exc:  # fail safe: a judge outage must not crash the run
            logger.warning("PhoenixEvalJudge evaluation failed: %s", exc)
            return JudgeVerdict(score=0.0, reasoning=f"phoenix-evals failed: {exc}")
        label = getattr(result, "label", None)
        raw_score = getattr(result, "score", None)
        if raw_score is not None:
            score = float(raw_score)
        elif label is not None:
            score = float(self._choices.get(label, 0.0))
        else:
            score = 0.0
        return JudgeVerdict(
            score=score,
            reasoning=getattr(result, "explanation", "") or "",
            raw={"label": label, "score": raw_score},
        )
