"""LLM-as-judge over the Anthropic Messages API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

# Constructor default for the Anthropic judge, named once so code and docs cannot
# drift apart; always overridable via config — never hard-coded at a call site.
DEFAULT_ANTHROPIC_JUDGE_MODEL = "claude-opus-4-8"

logger = logging.getLogger(__name__)


@JUDGES.register("anthropic", aliases=("claude",))
class AnthropicJudge(Judge):  # pragma: no cover - requires anthropic SDK + network
    """LLM-as-judge over the Anthropic Messages API. Model id comes from config.

    The optional live path for the behavioral-regression demo's "wire a real model"
    toggle. Default model is :data:`DEFAULT_ANTHROPIC_JUDGE_MODEL`, overridable via
    config — never hard-coded at a call site.

    Note: ``temperature`` is omitted by default. Sampling parameters are rejected
    (HTTP 400) on Opus 4.8 / 4.7; only set ``temperature`` for older models that accept
    it. The API key is read from ``ANTHROPIC_API_KEY`` (or passed explicitly), never
    embedded in source.

    ``client`` is the same dependency-injection seam ``OpenAIJudge`` and
    ``ModelTarget`` carry: a pre-built client, so an M8 pipeline can exercise
    this judge with neither the SDK installed nor a socket opened. When ``None``
    the real client is built, exactly as before.

    Unlike ``OpenAIJudge``, this holds at call time too: :meth:`evaluate` imports
    nothing and only calls ``client.messages.create``, so an injected client keeps
    the SDK out of the process entirely.
    """

    def __init__(
        self,
        model: str = DEFAULT_ANTHROPIC_JUDGE_MODEL,
        api_key: str | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        system: str | None = None,
        score_field: str = "score",
        client: Any | None = None,
    ):
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "AnthropicJudge requires anthropic. Install with: pip install 'langfuse-eval-harness[anthropic]'"
                ) from exc
            logger.debug("AnthropicJudge constructing SDK client")
            client = anthropic.Anthropic(api_key=api_key)
        else:
            logger.debug("AnthropicJudge using injected client")
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system = system or 'Respond ONLY with JSON: {"score": <0..1>, "reasoning": <str>}.'
        self.score_field = score_field

    def _extract_json(self, text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Could not extract JSON from the Anthropic response.")
        return json.loads(match.group(0))  # type: ignore[no-any-return]

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": [{"role": "user", "content": prompt}],
        }
        # Only forward temperature when explicitly set — it 400s on Opus 4.8 / 4.7.
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        resp = self.client.messages.create(**kwargs)
        text = "".join(block.text for block in resp.content if block.type == "text")
        try:
            parsed = self._extract_json(text)
            return JudgeVerdict(
                # Mirror OpenAIJudge: a missing score is a clean 0.0 verdict, not a parse failure.
                score=float(parsed.get(self.score_field, 0.0)),
                reasoning=str(parsed.get("reasoning", "")),
                raw=parsed,
            )
        except Exception as exc:
            # Mirror OpenAIJudge: a malformed/incomplete response yields a default
            # failure verdict rather than crashing the whole evaluation run.
            logger.warning("Returning default failure verdict due to parsing error: %s", exc)
            return JudgeVerdict(
                score=0.0,
                reasoning=f"Failed to parse Anthropic output: {exc}. Output was: {text}",
                raw={"content": text},
            )
