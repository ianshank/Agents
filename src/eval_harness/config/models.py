"""Versioned configuration models.

Everything that drives behaviour lives here as data: component selection,
parameters, sampling, gating thresholds. There are no behavioural literals in
the engine itself — defaults are declared on these models and overridable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

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
