"""A real, model-backed target (the LLM system-under-test).

``EchoTarget`` and ``CallableTarget`` (see :mod:`eval_harness.targets`) cover
wiring and arbitrary Python callables, but neither calls a real model. This
module adds ``ModelTarget`` — a ``TARGETS``-registered runner that sends a prompt
to an OpenAI-compatible, Amazon Bedrock, or Anthropic endpoint and returns the
model's raw completion text as a :class:`~eval_harness.core.types.TargetOutput`.

A target produces an output to be *scored*; it does not parse a JSON verdict the
way a judge does. So this reuses the **client-construction and retry patterns**
proven in :mod:`eval_harness.judges` rather than the judge classes themselves:
the architecture manifest keeps ``targets`` dependent on ``core`` and ``plugins``
only (importing ``judges`` would add an undeclared component edge and trip the
drift gate), and ``judges`` is a protected path. The handful of duplicated
client-construction lines are deliberate and documented in ADR 0013.

Everything is config-driven and no value is hard-coded: the provider, model id,
endpoint, sampling params and prompt template all come from config, and
credentials are sourced from environment variables only (never embedded in
source or committed config).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..core.interfaces import TargetRunner
from ..core.types import EvalItem, TargetOutput
from ..plugins import TARGETS

# Default system prompt is intentionally empty for a *target* — unlike a judge we
# do not coerce a JSON shape; the model answers the user prompt as-is.
_PROVIDERS = ("openai", "bedrock", "anthropic")

logger = logging.getLogger(__name__)


class ModelTargetConfig(BaseModel):
    """Single source of truth for :class:`ModelTarget`'s operational defaults AND
    validation (charter §4 invariant 5: every operational value is a ``*Config``
    field with a documented default, never a bare literal at the call site).
    ``ModelTarget.__init__`` constructs and validates one of these from its actual
    arguments — not just its own class-level defaults — so an out-of-range value
    (e.g. ``top_p=5.0``, ``retry_max_seconds &lt; retry_min_seconds``) raises
    ``pydantic.ValidationError`` at construction time instead of being silently
    accepted (``Registry.create`` passes an arbitrary config dict straight through
    to the constructor, with nothing else validating it).

    Declared here rather than in ``eval_harness.config.models``: the architecture
    manifest keeps the ``targets`` component dependent on ``core``/``plugins``
    only (see this module's docstring), so a typed config that ``targets`` owns
    stays local rather than crossing into ``config``.
    """

    max_tokens: int = Field(default=1024, gt=0, description="Max tokens in the model's completion.")
    max_retries: int = Field(
        default=5, ge=0, description="Retry attempts on a rate-limit error (openai provider only)."
    )
    # ge=0 (not gt=0): zero backoff is a legitimate choice (e.g. fast-failing tests),
    # not just a permissive default — see tests/test_model_target.py's rate-limit-retry
    # test, which passes retry_min_seconds=retry_max_seconds=0 deliberately.
    retry_min_seconds: float = Field(
        default=2.0, ge=0, description="Minimum exponential-backoff wait between retries, in seconds."
    )
    retry_max_seconds: float = Field(
        default=30.0, ge=0, description="Maximum exponential-backoff wait between retries, in seconds."
    )
    temperature: float | None = Field(
        default=0.0, description="Sampling temperature; omitted entirely if None (some models reject it)."
    )
    top_p: float = Field(default=1.0, gt=0, le=1.0, description="Nucleus sampling parameter.")
    prompt_template: str = Field(default="{prompt}", description="str.format template rendered over item.inputs.")

    @model_validator(mode="after")
    def _check_retry_bounds(self) -> ModelTargetConfig:
        if self.retry_max_seconds < self.retry_min_seconds:
            raise ValueError(
                f"retry_max_seconds ({self.retry_max_seconds}) must be >= retry_min_seconds ({self.retry_min_seconds})"
            )
        return self


_DEFAULTS = ModelTargetConfig()


@TARGETS.register("model", aliases=("llm",))
class ModelTarget(TargetRunner):
    """Call a real LLM and return its completion text as the target output.

    Parameters (all from config ``params``; see ADR 0013):

    * ``provider`` — ``openai`` | ``bedrock`` | ``anthropic``.
    * ``model`` — the model id (required; no default literal).
    * ``base_url`` — OpenAI-compatible endpoint (openai provider only).
    * ``api_key`` — optional; clients also read the provider's env var when ``None``.
    * ``region`` — AWS region (bedrock only).
    * ``prompt_template`` — ``str.format`` template over ``item.inputs``
      (default ``"{prompt}"``).
    * ``system`` — optional system prompt.
    * ``max_tokens`` / ``temperature`` / ``top_p`` — sampling params.
    * ``extra_body`` — passthrough body for OpenAI-compatible servers (e.g. Nemotron).
    * ``max_retries`` / ``retry_min_seconds`` / ``retry_max_seconds`` — rate-limit
      backoff for the openai provider.
    * ``client`` — dependency-injection seam: a pre-built client (used by tests so
      no real SDK/network is needed). When ``None`` the real client is built.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        region: str | None = None,
        prompt_template: str = _DEFAULTS.prompt_template,
        system: str | None = None,
        max_tokens: int = _DEFAULTS.max_tokens,
        temperature: float | None = _DEFAULTS.temperature,
        top_p: float = _DEFAULTS.top_p,
        extra_body: dict[str, Any] | None = None,
        max_retries: int = _DEFAULTS.max_retries,
        retry_min_seconds: float = _DEFAULTS.retry_min_seconds,
        retry_max_seconds: float = _DEFAULTS.retry_max_seconds,
        client: Any | None = None,
    ) -> None:
        if provider not in _PROVIDERS:
            raise ValueError(f"provider must be one of {_PROVIDERS}, got {provider!r}")
        # Validates the actual arguments (not just ModelTargetConfig's own class-level
        # defaults) — raises pydantic.ValidationError on an out-of-range value instead
        # of silently accepting it. See ModelTargetConfig's docstring.
        config = ModelTargetConfig(
            max_tokens=max_tokens,
            max_retries=max_retries,
            retry_min_seconds=retry_min_seconds,
            retry_max_seconds=retry_max_seconds,
            temperature=temperature,
            top_p=top_p,
            prompt_template=prompt_template,
        )
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.region = region
        self.prompt_template = config.prompt_template
        self.system = system
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature
        self.top_p = config.top_p
        self.extra_body = extra_body or {}
        self.max_retries = config.max_retries
        self.retry_min_seconds = config.retry_min_seconds
        self.retry_max_seconds = config.retry_max_seconds
        # DI seam: tests inject a stub; production builds the real SDK client.
        self.client = client if client is not None else self._build_client()

    def is_deterministic(self) -> bool | None:
        """``temperature == 0.0`` is the only case treated as deterministic.

        ``temperature is None`` means the param is omitted entirely (some models
        reject it) — the provider's own default sampling behaviour is opaque to
        this harness, so that case is genuinely unknown, not ``False``.
        """
        if self.temperature is None:
            return None
        return self.temperature == 0.0

    # ------------------------------------------------------------------ client
    def _build_client(self) -> Any:  # pragma: no cover - pure dispatch to SDK-network construction
        if self.provider == "openai":
            return self._build_openai_client()
        if self.provider == "bedrock":
            return self._build_bedrock_client()
        return self._build_anthropic_client()

    def _build_openai_client(self) -> Any:  # pragma: no cover - needs openai SDK + network
        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "ModelTarget(provider='openai') requires openai. "
                "Install with: pip install 'langfuse-eval-harness[openai]'"
            ) from exc
        return openai.OpenAI(base_url=self.base_url, api_key=self.api_key)

    def _build_bedrock_client(self) -> Any:  # pragma: no cover - needs boto3 + network
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "ModelTarget(provider='bedrock') requires boto3. "
                "Install with: pip install 'langfuse-eval-harness[bedrock]'"
            ) from exc
        return boto3.client("bedrock-runtime", region_name=self.region)

    def _build_anthropic_client(self) -> Any:  # pragma: no cover - needs anthropic SDK + network
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "ModelTarget(provider='anthropic') requires anthropic. "
                "Install with: pip install 'langfuse-eval-harness[anthropic]'"
            ) from exc
        return anthropic.Anthropic(api_key=self.api_key)

    # ------------------------------------------------------------------- prompt
    def _render_prompt(self, item: EvalItem) -> str:
        """Build the prompt from ``item.inputs`` via ``prompt_template``.

        Reuses the same ``str.format`` convention as the agent-core adapter's
        ``judge_prompt_template``. A missing template key raises ``KeyError``,
        which :meth:`run` surfaces as a scored ``TargetOutput.error``.
        """
        return self.prompt_template.format(**item.inputs)

    # ---------------------------------------------------------------- execution
    def run(self, item: EvalItem) -> TargetOutput:
        start = time.perf_counter()
        try:
            prompt = self._render_prompt(item)
            text = self._complete(prompt)
            latency = (time.perf_counter() - start) * 1000
            return TargetOutput(
                output=text,
                latency_ms=latency,
                metadata={"provider": self.provider, "model": self.model},
            )
        except Exception as exc:  # surface model/transport failures as scored errors
            latency = (time.perf_counter() - start) * 1000
            logger.error(
                "ModelTarget run failed (provider=%s, model=%s): %s", self.provider, self.model, exc, exc_info=True
            )
            return TargetOutput(output=None, error=str(exc), latency_ms=latency)

    def _complete(self, prompt: str) -> str:
        if self.provider == "openai":
            return self._complete_openai(prompt)
        if self.provider == "bedrock":
            return self._complete_bedrock(prompt)
        return self._complete_anthropic(prompt)

    def _complete_openai(self, prompt: str) -> str:
        """Stream an OpenAI-compatible chat completion and join the content.

        Mirrors ``OpenAIJudge.evaluate``: tenacity backoff on ``RateLimitError``
        and the same streamed-delta accumulation, returning the raw text.
        """
        import openai
        from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

        messages: list[dict[str, str]] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": prompt})

        @retry(
            retry=retry_if_exception_type(openai.RateLimitError),
            wait=wait_exponential(multiplier=1, min=self.retry_min_seconds, max=self.retry_max_seconds),
            stop=stop_after_attempt(self.max_retries),
            reraise=True,
        )
        def _call_api() -> Any:
            logger.debug("Calling OpenAI-compatible API: model=%s, base_url=%s", self.model, self.base_url)
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_tokens,
                stream=True,
                extra_body=self.extra_body,
            )

        completion = _call_api()
        content_chunks: list[str] = []
        for chunk in completion:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content is not None:
                content_chunks.append(delta.content)
        return "".join(content_chunks)

    def _complete_bedrock(self, prompt: str) -> str:
        """Invoke a Bedrock model and return the first text block.

        Mirrors ``BedrockJudge``'s ``invoke_model`` request/response shape.
        """
        import json

        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.system:
            body["system"] = self.system
        if self.temperature is not None:
            body["temperature"] = self.temperature
        logger.debug("Calling Bedrock API: model=%s, region=%s", self.model, self.region)
        resp = self.client.invoke_model(modelId=self.model, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        return str(payload["content"][0]["text"])

    def _complete_anthropic(self, prompt: str) -> str:
        """Call the Anthropic Messages API and join its text blocks.

        Mirrors ``AnthropicJudge``: ``temperature`` is omitted unless explicitly
        set, because Opus 4.x rejects sampling params (HTTP 400).
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.system:
            kwargs["system"] = self.system
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        logger.debug("Calling Anthropic API: model=%s", self.model)
        resp = self.client.messages.create(**kwargs)
        return "".join(block.text for block in resp.content if block.type == "text")
