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


class EvalConfig(BaseModel):
    schema_version: str
    run: RunSettings = Field(default_factory=RunSettings)
    dataset: ComponentSpec
    target: ComponentSpec
    scorers: list[ComponentSpec] = Field(default_factory=list)
    judge: ComponentSpec | None = None
    judge_budget: JudgeBudgetConfig | None = None
    sinks: list[ComponentSpec] = Field(default_factory=list)
    gate: GateConfig | None = None

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"EvalConfig expects schema_version {SCHEMA_VERSION!r}; got {v!r}. "
                "Load via config.loader so older versions are migrated first."
            )
        return v
