"""LLM-as-judge over OpenAI-compatible APIs (including NVIDIA Nemotron and LM Studio)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

# OpenAIJudge.evaluate's rate-limit backoff, named once so code and docs cannot
# drift apart (charter §4 invariant 5). Not exposed as constructor params, unlike
# ModelTargetConfig's identical values (targets/model.py) — OpenAIJudge's other
# constructor defaults are also bare literals today, so promoting only the retry
# knob to a config field would be an inconsistent partial migration; a full
# *Config class for this judge is a separate, larger change than the naming fix
# these constants are for.
DEFAULT_RETRY_WAIT_MIN_SECONDS = 2
DEFAULT_RETRY_WAIT_MAX_SECONDS = 30
DEFAULT_RETRY_MAX_ATTEMPTS = 5

logger = logging.getLogger(__name__)


@JUDGES.register("openai")
class OpenAIJudge(Judge):
    """LLM-as-judge over OpenAI-compatible APIs (including NVIDIA Nemotron & LM Studio).

    ``client`` is a dependency-injection seam mirroring ``ModelTarget``'s
    (``targets/model.py``): a pre-built client, so **construction** needs neither
    the SDK nor a network. When ``None`` the real client is built, exactly as
    before — an absent injection is indistinguishable from the pre-seam
    behaviour for every existing caller.

    Scoped deliberately to construction: :meth:`evaluate` still does ``import
    openai`` for ``RateLimitError`` in its retry predicate, so an injected client
    removes the *client build* and the socket, not the import. (``AnthropicJudge``
    differs — its ``evaluate`` imports nothing, so an injected client there avoids
    the SDK entirely.)

    The seam is not a convenience. Without it this constructor built a real
    ``openai.OpenAI`` unconditionally, so an M8 pipeline naming this judge
    attempted real network egress from CI *and still reported green*: the
    engine converts a scorer exception into a ``0.0``-valued ``ScoreResult``
    with a ``"scorer error: "`` comment rather than raising. An offline matrix
    cell for this judge is unreachable without it.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        top_p: float = 1.0,
        system: str | None = None,
        score_field: str = "score",
        extra_body: dict[str, Any] | None = None,
        client: Any | None = None,
    ):
        if client is None:
            try:
                import openai
            except ImportError as exc:  # pragma: no cover - openai is a required extra; not reachable when installed
                raise RuntimeError(
                    "OpenAIJudge requires openai. Install with: pip install 'langfuse-eval-harness[openai]'"
                ) from exc

            # We don't want to fail immediately if api_key is missing because it might be picked up by the openai client from env vars,
            # or it might not be needed for LM studio.
            logger.debug("OpenAIJudge constructing SDK client")
            client = openai.OpenAI(base_url=base_url, api_key=api_key)
        else:
            logger.debug("OpenAIJudge using injected client")
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.system = system or 'Respond ONLY with JSON: {"score": <0..1>, "reasoning": <str>}.'
        self.score_field = score_field
        self.extra_body = extra_body or {}

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Robustly extract JSON from the LLM response, ignoring markdown wrappers."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            json_str = match.group(0)
            try:
                return json.loads(json_str)  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                logger.error("Failed to parse extracted JSON: %s", json_str, exc_info=True)
                raise
        logger.error("No JSON object found in response: %s", text)
        raise ValueError("Could not extract JSON from the LLM response.")

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        import openai
        from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

        messages: list[dict[str, str]] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": prompt})

        @retry(
            retry=retry_if_exception_type(openai.RateLimitError),
            wait=wait_exponential(multiplier=1, min=DEFAULT_RETRY_WAIT_MIN_SECONDS, max=DEFAULT_RETRY_WAIT_MAX_SECONDS),
            stop=stop_after_attempt(DEFAULT_RETRY_MAX_ATTEMPTS),
            reraise=True,
        )
        def _call_api() -> Any:
            logger.debug("Calling OpenAI API: model=%s, base_url=%s", self.model, self.client.base_url)
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_tokens,
                stream=True,
                extra_body=self.extra_body,
            )

        try:
            completion = _call_api()
        except Exception as exc:
            logger.error("OpenAI API call failed: %s", exc, exc_info=True)
            raise

        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []

        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_chunks.append(reasoning)
            if delta.content is not None:
                content_chunks.append(delta.content)

        full_content = "".join(content_chunks)
        full_reasoning = "".join(reasoning_chunks)

        logger.debug(
            "Received response: content_length=%d, reasoning_length=%d", len(full_content), len(full_reasoning)
        )

        try:
            parsed = self._extract_json(full_content)
        except Exception as exc:
            # If parsing fails, return a default verdict with the error
            logger.warning("Returning default failure verdict due to parsing error: %s", exc)
            return JudgeVerdict(
                score=0.0,
                reasoning=f"Failed to parse LLM output: {exc}. Output was: {full_content}",
                raw={"content": full_content, "reasoning_content": full_reasoning},
            )

        # If Nemotron gave us explicit reasoning via streaming, prepend or use it
        extracted_reasoning = str(parsed.get("reasoning", ""))
        final_reasoning = extracted_reasoning
        if full_reasoning:
            final_reasoning = f"[thinking]\n{full_reasoning}\n[/thinking]\n{extracted_reasoning}"

        return JudgeVerdict(
            score=float(parsed.get(self.score_field, 0.0)),
            reasoning=final_reasoning.strip(),
            raw={"parsed": parsed, "raw_content": full_content, "reasoning_content": full_reasoning},
        )

    def attach_client(self, client: Any) -> None:
        """Attach LangfuseClient and switch to the traced OpenAI wrapper if active."""
        from ..langfuse_client import SDKLangfuseClient

        if isinstance(client, SDKLangfuseClient):
            try:
                from langfuse.openai import OpenAI as LFOpenAI

                self.client = LFOpenAI(
                    base_url=str(self.client.base_url) if self.client.base_url else None, api_key=self.client.api_key
                )
                logger.info("Successfully attached SDKLangfuseClient and enabled Langfuse OpenAI tracing.")
            except ImportError:
                logger.warning("Could not import langfuse.openai.OpenAI. Tracing is disabled.")
