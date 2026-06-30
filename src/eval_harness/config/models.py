"""Versioned configuration models.

Everything that drives behaviour lives here as data: component selection,
parameters, sampling, gating thresholds. There are no behavioural literals in
the engine itself — defaults are declared on these models and overridable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ..version import SCHEMA_VERSION


class ComponentSpec(BaseModel):
    """Selects a registered component by ``type`` and configures it."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class RunSettings(BaseModel):
    name: str = "eval-run"
    run_id: str | None = None
    seed: int = 0
    sample_rate: float = 1.0
    fail_fast: bool = False
    max_workers: int = Field(
        default=1,
        ge=1,
        description=(
            "Maximum number of concurrent worker threads for item evaluation. "
            "1 = sequential (default, identical to legacy behaviour). "
            ">1 = parallel via ThreadPoolExecutor. Note: Langfuse per-item "
            "trace linking is unavailable in parallel mode."
        ),
    )

    @field_validator("sample_rate")
    @classmethod
    def _check_rate(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("sample_rate must be between 0.0 and 1.0")
        return v


class JudgeBudgetConfig(BaseModel):
    """Optional per-run cost cap for judge calls (F-022).

    The cap is a cumulative budget, not a time-windowed rate limit. Each judge
    ``evaluate`` reserves ``cost_per_call`` against an ``agent_core.BudgetLedger``
    *before* the call (so the cap holds under parallel execution); when the cap is
    exhausted the wrapped judge either raises or returns a sentinel verdict, per
    ``on_exceeded``. Disabled by default and fully backwards-compatible — when
    absent or ``enabled=False`` nothing is wrapped and agent_core is not imported.
    """

    enabled: bool = False
    cap: float | None = Field(
        default=None,
        gt=0,
        description="Total budget in cost units (e.g. max number of calls when cost_per_call=1). Required when enabled.",
    )
    cost_per_call: float = Field(
        default=1.0,
        gt=0,
        description=(
            "Cost charged per judge call, in the same units as 'cap'. Use 1.0 for a request budget, "
            "or a per-call token estimate for a token budget (no live token signal exists at the judge call site)."
        ),
    )
    on_exceeded: str = "raise"  # "raise" | "skip"
    skip_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sentinel verdict score returned when the budget is exhausted and on_exceeded='skip'.",
    )

    @field_validator("on_exceeded")
    @classmethod
    def _check_on_exceeded(cls, v: str) -> str:
        if v not in ("raise", "skip"):
            raise ValueError("on_exceeded must be 'raise' or 'skip'")
        return v

    @model_validator(mode="after")
    def _require_cap_when_enabled(self) -> JudgeBudgetConfig:
        # Fail fast at config-parse time rather than at engine construction.
        if self.enabled and self.cap is None:
            raise ValueError("judge_budget.cap must be set (> 0) when judge budget is enabled")
        return self


class PromptSourceConfig(BaseModel):
    """Where a judge's system prompt comes from (F-026).

    ``source='yaml'`` (default) uses the inline ``text`` — the pre-F-026 behaviour.
    ``source='langfuse'`` pulls the named prompt from the Langfuse prompt registry,
    with a config-driven fallback to ``text`` when Langfuse is unavailable or the
    prompt is missing (mirrors the no-op tracing fallback). Fully optional and
    additive, so ``SCHEMA_VERSION`` is unchanged.
    """

    source: str = "yaml"
    text: str | None = None  # inline prompt / fallback text
    name: str | None = None  # Langfuse prompt name (required when source='langfuse')
    version: int | None = None  # specific Langfuse prompt version
    label: str | None = None  # Langfuse prompt label (e.g. 'production')

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if v not in ("yaml", "langfuse"):
            raise ValueError("prompt source must be 'yaml' or 'langfuse'")
        return v

    @model_validator(mode="after")
    def _require_name_for_langfuse(self) -> PromptSourceConfig:
        if self.source == "langfuse" and not self.name:
            raise ValueError("judge_prompt.name is required when source='langfuse'")
        if self.source == "yaml" and self.text is None:
            raise ValueError("judge_prompt.text is required when source='yaml'")
        return self


class GateRule(BaseModel):
    score: str
    metric: str = "mean"  # "mean" | "pass_rate"
    min: float | None = None
    max: float | None = None

    @field_validator("metric")
    @classmethod
    def _check_metric(cls, v: str) -> str:
        if v not in ("mean", "pass_rate"):
            raise ValueError("metric must be 'mean' or 'pass_rate'")
        return v


class GateConfig(BaseModel):
    rules: list[GateRule] = Field(default_factory=list)


class ModelSpec(BaseModel):
    """A named target (model / system-under-test) in a multi-model comparison (F-024)."""

    name: str
    target: ComponentSpec


class ComparisonConfig(BaseModel):
    """Run the same dataset/scorers against several targets and compare them (F-024).

    Additive and optional, so ``SCHEMA_VERSION`` is unchanged. ``baseline`` (a model
    name) defines the reference for per-metric deltas; ``rank_by`` selects the score
    used to rank models (defaults to the first aggregate score), with ``rank_metric``
    choosing mean vs pass_rate.
    """

    models: list[ModelSpec] = Field(min_length=2)
    baseline: str | None = None
    rank_by: str | None = None
    rank_metric: str = "mean"

    @field_validator("rank_metric")
    @classmethod
    def _check_rank_metric(cls, v: str) -> str:
        if v not in ("mean", "pass_rate"):
            raise ValueError("rank_metric must be 'mean' or 'pass_rate'")
        return v

    @model_validator(mode="after")
    def _check_models(self) -> ComparisonConfig:
        names = [m.name for m in self.models]
        if len(names) != len(set(names)):
            raise ValueError("comparison model names must be unique")
        if self.baseline is not None and self.baseline not in names:
            raise ValueError(f"comparison.baseline {self.baseline!r} is not one of the model names")
        return self


class ABCampaignConfig(BaseModel):
    """Persistent A/B eval campaign with statistical-significance testing (F-025).

    Two named arms (reusing ``ModelSpec``) are run over the same dataset/scorers;
    per-arm pass/total counts for ``score`` accumulate across runs in a store, and
    significance is decided from agent_core Wilson intervals — never claimed below
    the ``min_sample`` power floor. Additive/optional, so ``SCHEMA_VERSION`` is
    unchanged.
    """

    campaign_id: str
    arm_a: ModelSpec
    arm_b: ModelSpec
    score: str
    wilson_z: float = Field(default=1.96, gt=0)
    min_sample: int = Field(default=30, ge=1)

    @model_validator(mode="after")
    def _distinct_arms(self) -> ABCampaignConfig:
        if self.arm_a.name == self.arm_b.name:
            raise ValueError("ab_campaign arm_a and arm_b must have distinct names")
        return self


class EvalConfig(BaseModel):
    schema_version: str
    run: RunSettings = Field(default_factory=RunSettings)
    dataset: ComponentSpec
    target: ComponentSpec
    scorers: list[ComponentSpec] = Field(default_factory=list)
    judge: ComponentSpec | None = None
    judge_budget: JudgeBudgetConfig | None = None
    judge_prompt: PromptSourceConfig | None = None
    sinks: list[ComponentSpec] = Field(default_factory=list)
    gate: GateConfig | None = None
    comparison: ComparisonConfig | None = None
    ab_campaign: ABCampaignConfig | None = None

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"EvalConfig expects schema_version {SCHEMA_VERSION!r}; got {v!r}. "
                "Load via config.loader so older versions are migrated first."
            )
        return v
