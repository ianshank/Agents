"""Built-in judges. ``mock`` is deterministic and offline; ``bedrock`` is real."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

logger = logging.getLogger(__name__)


@JUDGES.register("mock", aliases=("deterministic",))
class MockJudge(Judge):
    """Deterministic judge driven entirely by config.

    ``rules`` is a list of ``{contains: str, score: float}``; the first rule whose
    substring is found in the prompt wins, else ``default_score`` is returned.
    """

    def __init__(self, default_score: float = 1.0, rules: list[dict] | None = None):
        self.default_score = float(default_score)
        self.rules = rules or []

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        for rule in self.rules:
            needle = rule.get("contains", "")
            if needle and needle in prompt:
                score = float(rule["score"])
                return JudgeVerdict(score=score, reasoning=f"matched rule {needle!r}")
        return JudgeVerdict(score=self.default_score, reasoning="default")


@JUDGES.register("bedrock")
class BedrockJudge(Judge):  # pragma: no cover - requires boto3 + network
    """LLM-as-judge over Amazon Bedrock. Model id and region come from config."""

    def __init__(
        self,
        model_id: str,
        region: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
        system: str | None = None,
        score_field: str = "score",
    ):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "BedrockJudge requires boto3. Install with: pip install 'langfuse-eval-harness[bedrock]'"
            ) from exc
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system = system or 'Respond ONLY with JSON: {"score": <0..1>, "reasoning": <str>}.'
        self.score_field = score_field

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": self.system,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = self._client.invoke_model(modelId=self.model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        text = payload["content"][0]["text"]
        parsed = json.loads(text)
        return JudgeVerdict(
            score=float(parsed[self.score_field]),
            reasoning=str(parsed.get("reasoning", "")),
            raw=parsed,
        )


@JUDGES.register("openai")
class OpenAIJudge(Judge):
    """LLM-as-judge over OpenAI-compatible APIs (including NVIDIA Nemotron & LM Studio)."""

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
    ):
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - openai is a required extra; not reachable when installed
            raise RuntimeError(
                "OpenAIJudge requires openai. Install with: pip install 'langfuse-eval-harness[openai]'"
            ) from exc

        # We don't want to fail immediately if api_key is missing because it might be picked up by the openai client from env vars,
        # or it might not be needed for LM studio.
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
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
            wait=wait_exponential(multiplier=1, min=2, max=30),
            stop=stop_after_attempt(5),
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
