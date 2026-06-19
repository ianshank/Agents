"""Built-in judges. ``mock`` is deterministic and offline; ``bedrock`` is real."""

from __future__ import annotations

import json
import logging
import re
from importlib import import_module
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

logger = logging.getLogger(__name__)

DEFAULT_MOCK_JUDGE_SCORE = 1.0
DEFAULT_BEDROCK_MAX_TOKENS = 512
DEFAULT_BEDROCK_TEMPERATURE = 0.0
DEFAULT_BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"
DEFAULT_JUDGE_SYSTEM_PROMPT = 'Respond ONLY with JSON: {"score": <0..1>, "reasoning": <str>}.'
DEFAULT_OPENAI_MAX_TOKENS = 4096
DEFAULT_OPENAI_TEMPERATURE = 0.0
DEFAULT_OPENAI_TOP_P = 1.0
DEFAULT_OPENAI_SCORE_FIELD = "score"
DEFAULT_OPENAI_STREAM = True
DEFAULT_OPENAI_FAILURE_SCORE = 0.0
DEFAULT_OPENAI_RETRY_ATTEMPTS = 5
DEFAULT_OPENAI_RETRY_WAIT_MULTIPLIER_SECONDS = 1.0
DEFAULT_OPENAI_RETRY_WAIT_MIN_SECONDS = 2.0
DEFAULT_OPENAI_RETRY_WAIT_MAX_SECONDS = 30.0
LANGFUSE_OPENAI_MODULE = "langfuse.openai"
LANGFUSE_OPENAI_CLIENT_ATTR = "OpenAI"


def _require_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_non_negative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


@JUDGES.register("mock", aliases=("deterministic",))
class MockJudge(Judge):
    """Deterministic judge driven entirely by config.

    ``rules`` is a list of ``{contains: str, score: float}``; the first rule whose
    substring is found in the prompt wins, else ``default_score`` is returned.
    """

    def __init__(self, default_score: float = DEFAULT_MOCK_JUDGE_SCORE, rules: list[dict[str, Any]] | None = None):
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
class BedrockJudge(Judge):
    """LLM-as-judge over Amazon Bedrock. Model id and region come from config."""

    def __init__(
        self,
        model_id: str,
        region: str | None = None,
        max_tokens: int = DEFAULT_BEDROCK_MAX_TOKENS,
        temperature: float = DEFAULT_BEDROCK_TEMPERATURE,
        system: str | None = None,
        score_field: str = "score",
        anthropic_version: str = DEFAULT_BEDROCK_ANTHROPIC_VERSION,
    ):
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "BedrockJudge requires boto3. Install with: pip install 'langfuse-eval-harness[bedrock]'"
            ) from exc
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system = system or DEFAULT_JUDGE_SYSTEM_PROMPT
        self.score_field = score_field
        self.anthropic_version = anthropic_version

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        body = {
            "anthropic_version": self.anthropic_version,
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
        max_tokens: int = DEFAULT_OPENAI_MAX_TOKENS,
        temperature: float = DEFAULT_OPENAI_TEMPERATURE,
        top_p: float = DEFAULT_OPENAI_TOP_P,
        system: str | None = None,
        score_field: str = DEFAULT_OPENAI_SCORE_FIELD,
        extra_body: dict[str, Any] | None = None,
        stream: bool = DEFAULT_OPENAI_STREAM,
        failure_score: float = DEFAULT_OPENAI_FAILURE_SCORE,
        retry_attempts: int = DEFAULT_OPENAI_RETRY_ATTEMPTS,
        retry_wait_multiplier_seconds: float = DEFAULT_OPENAI_RETRY_WAIT_MULTIPLIER_SECONDS,
        retry_wait_min_seconds: float = DEFAULT_OPENAI_RETRY_WAIT_MIN_SECONDS,
        retry_wait_max_seconds: float = DEFAULT_OPENAI_RETRY_WAIT_MAX_SECONDS,
        langfuse_openai_module: str = LANGFUSE_OPENAI_MODULE,
    ):
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        _require_non_negative("temperature", temperature)
        _require_positive("top_p", top_p)
        _require_non_negative("failure_score", failure_score)
        if retry_attempts < 1:
            raise ValueError("retry_attempts must be >= 1")
        _require_positive("retry_wait_multiplier_seconds", retry_wait_multiplier_seconds)
        _require_non_negative("retry_wait_min_seconds", retry_wait_min_seconds)
        _require_non_negative("retry_wait_max_seconds", retry_wait_max_seconds)
        if retry_wait_min_seconds > retry_wait_max_seconds:
            raise ValueError("retry_wait_min_seconds must be <= retry_wait_max_seconds")
        if not score_field:
            raise ValueError("score_field must not be empty")
        if not langfuse_openai_module:
            raise ValueError("langfuse_openai_module must not be empty")

        try:
            import openai
        except ImportError as exc:  # pragma: no cover - openai is a required extra; not reachable when installed
            raise RuntimeError(
                "OpenAIJudge requires openai. Install with: pip install 'langfuse-eval-harness[openai]'"
            ) from exc

        # We don't want to fail immediately if api_key is missing because it might be picked up by the openai client from env vars,
        # or it might not be needed for LM studio.
        self.client: Any = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.system = system or DEFAULT_JUDGE_SYSTEM_PROMPT
        self.score_field = score_field
        self.extra_body = extra_body or {}
        self.stream = stream
        self.failure_score = failure_score
        self.retry_attempts = retry_attempts
        self.retry_wait_multiplier_seconds = retry_wait_multiplier_seconds
        self.retry_wait_min_seconds = retry_wait_min_seconds
        self.retry_wait_max_seconds = retry_wait_max_seconds
        self.langfuse_openai_module = langfuse_openai_module

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
            wait=wait_exponential(
                multiplier=self.retry_wait_multiplier_seconds,
                min=self.retry_wait_min_seconds,
                max=self.retry_wait_max_seconds,
            ),
            stop=stop_after_attempt(self.retry_attempts),
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
                stream=self.stream,
                extra_body=self.extra_body,
            )

        try:
            completion = _call_api()
        except Exception as exc:
            logger.error("OpenAI API call failed: %s", exc, exc_info=True)
            raise

        if self.stream:
            full_content, full_reasoning = self._collect_streaming_completion(completion)
        else:
            full_content, full_reasoning = self._collect_completion_message(completion)

        logger.debug(
            "Received response: content_length=%d, reasoning_length=%d", len(full_content), len(full_reasoning)
        )

        try:
            parsed = self._extract_json(full_content)
        except Exception as exc:
            # If parsing fails, return a default verdict with the error
            logger.warning("Returning default failure verdict due to parsing error: %s", exc)
            return JudgeVerdict(
                score=self.failure_score,
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

    def _collect_streaming_completion(self, completion: Any) -> tuple[str, str]:
        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []

        for chunk in completion:
            choices = getattr(chunk, "choices", ())
            if not choices:
                continue
            delta = choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_chunks.append(reasoning)
            content = getattr(delta, "content", None)
            if content is not None:
                content_chunks.append(content)

        return "".join(content_chunks), "".join(reasoning_chunks)

    def _collect_completion_message(self, completion: Any) -> tuple[str, str]:
        choices = getattr(completion, "choices", ())
        if not choices:
            return "", ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return "", ""
        content = getattr(message, "content", None) or ""
        reasoning = getattr(message, "reasoning_content", None) or ""
        return str(content), str(reasoning)

    def _load_langfuse_openai_client(self) -> Any:
        module = import_module(self.langfuse_openai_module)
        return getattr(module, LANGFUSE_OPENAI_CLIENT_ATTR)

    def attach_client(self, client: Any) -> None:
        """Attach LangfuseClient and switch to the traced OpenAI wrapper if active."""
        from ..langfuse_client import SDKLangfuseClient

        if isinstance(client, SDKLangfuseClient):
            try:
                lf_openai = self._load_langfuse_openai_client()

                self.client = lf_openai(
                    base_url=str(self.client.base_url) if self.client.base_url else None, api_key=self.client.api_key
                )
                logger.info("Successfully attached SDKLangfuseClient and enabled Langfuse OpenAI tracing.")
            except (ImportError, AttributeError):
                logger.warning("Could not import langfuse.openai.OpenAI. Tracing is disabled.")
