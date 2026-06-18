"""Configuration schema.

Every tunable in the framework lives here as a dataclass field with a documented
default. Business logic reads these values; it never embeds literals. Configs are
versioned and round-trip through ``to_dict``/``from_dict`` with automatic
migration of older payloads, which is what makes persisted configs
backwards-compatible across releases.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .version import SCHEMA_VERSION, migrate_config


class ConfigError(ValueError):
    """Raised when a configuration value is structurally invalid."""


@dataclass(frozen=True)
class BudgetConfig:
    cap_units: float = 600_000.0  # total cost budget per run (tokens/units)
    reserve_fraction: float = 0.15  # fraction held back for the final report

    def __post_init__(self) -> None:
        if self.cap_units <= 0:
            raise ConfigError("budget.cap_units must be > 0")
        if not 0.0 <= self.reserve_fraction < 1.0:
            raise ConfigError("budget.reserve_fraction must be in [0, 1)")


@dataclass(frozen=True)
class LoopConfig:
    max_cycles: int = 5  # safety backstop, not the primary control
    convergence_epsilon: float = 0.05  # max confidence delta to call it converged
    absolute_max_cycles: int = 1000  # controller hard limit; guards gate misconfig

    def __post_init__(self) -> None:
        if self.max_cycles < 1:
            raise ConfigError("loop.max_cycles must be >= 1")
        if self.convergence_epsilon <= 0:
            raise ConfigError("loop.convergence_epsilon must be > 0")
        if self.absolute_max_cycles < self.max_cycles:
            raise ConfigError("loop.absolute_max_cycles must be >= max_cycles")


@dataclass(frozen=True)
class CalibrationConfig:
    n_bins: int = 10
    ece_target: float = 0.05
    mce_target: float = 0.12
    auroc_target: float = 0.80
    wilson_z: float = 1.96  # 95% interval by default

    def __post_init__(self) -> None:
        if self.n_bins < 1:
            raise ConfigError("calibration.n_bins must be >= 1")
        for name in ("ece_target", "mce_target"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ConfigError(f"calibration.{name} must be in [0, 1]")
        if not 0.0 <= self.auroc_target <= 1.0:
            raise ConfigError("calibration.auroc_target must be in [0, 1]")
        if self.wilson_z <= 0:
            raise ConfigError("calibration.wilson_z must be > 0")


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    fmt: str = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"


@dataclass(frozen=True)
class SanitizerConfig:
    """Configuration for the prompt-injection sanitizer."""

    risk_block_threshold: float = 0.80
    risk_aggregation: str = "max"  # "max" | "weighted_sum"
    default_redaction: str = "[redacted]"
    severity_weights: tuple[tuple[str, float], ...] = (
        ("instruction_override", 1.0),
        ("role_hijack", 0.9),
        ("delimiter_injection", 0.6),
        ("exfiltration", 1.0),
        ("prompt_leak", 0.7),
    )
    enabled_categories: tuple[str, ...] = ()  # () = all registered categories

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled_categories", tuple(self.enabled_categories))
        object.__setattr__(
            self,
            "severity_weights",
            tuple((str(k), float(v)) for k, v in self.severity_weights),
        )
        if not 0.0 <= self.risk_block_threshold <= 1.0:
            raise ConfigError("sanitizer.risk_block_threshold must be in [0, 1]")
        if self.risk_aggregation not in ("max", "weighted_sum"):
            raise ConfigError("sanitizer.risk_aggregation must be 'max' or 'weighted_sum'")
        for cat, w in self.severity_weights:
            if not 0.0 <= w <= 1.0:
                raise ConfigError(f"sanitizer.severity_weights[{cat!r}] must be in [0, 1]")

    @property
    def weights(self) -> dict[str, float]:
        return dict(self.severity_weights)


@dataclass(frozen=True)
class GoldenConfig:
    train_ratio: float = 0.6
    calibration_ratio: float = 0.2
    test_ratio: float = 0.2
    split_seed: int = 1729

    def __post_init__(self) -> None:
        total = self.train_ratio + self.calibration_ratio + self.test_ratio
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ConfigError("golden ratios must sum to 1.0")
        for name in ("train_ratio", "calibration_ratio", "test_ratio"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ConfigError(f"golden.{name} must be in [0, 1]")


@dataclass(frozen=True)
class RecalibrationConfig:
    default_calibrator: str = "isotonic"
    fallback_policy: str = "global"  # "global" | "error"
    temperature_search_lo: float = 1e-2  # golden-section bracket lower bound
    temperature_search_hi: float = 1e2  # golden-section bracket upper bound
    temperature_max_iter: int = 50
    temperature_tol: float = 1e-6
    clamp_eps: float = 1e-6  # p clamped to [eps, 1-eps] before logit

    def __post_init__(self) -> None:
        if self.default_calibrator not in ("isotonic", "temperature"):
            raise ConfigError(
                f"recalibration.default_calibrator must be 'isotonic' or 'temperature';"
                f" got {self.default_calibrator!r}"
            )
        if self.fallback_policy not in ("global", "error"):
            raise ConfigError("recalibration.fallback_policy must be 'global' or 'error'")
        if not 0.0 < self.temperature_search_lo < self.temperature_search_hi:
            raise ConfigError("recalibration temperature bracket must satisfy 0 < lo < hi")
        if self.temperature_max_iter < 1:
            raise ConfigError("recalibration.temperature_max_iter must be >= 1")
        if not 0.0 < self.clamp_eps < 0.5:
            raise ConfigError("recalibration.clamp_eps must be in (0, 0.5)")


@dataclass(frozen=True)
class FrameworkConfig:
    version: str = SCHEMA_VERSION
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    sanitizer: SanitizerConfig = field(default_factory=SanitizerConfig)
    golden: GoldenConfig = field(default_factory=GoldenConfig)
    recalibration: RecalibrationConfig = field(default_factory=RecalibrationConfig)

    @property
    def reserve_units(self) -> float:
        return self.budget.cap_units * self.budget.reserve_fraction

    @property
    def loop_ceiling_units(self) -> float:
        """Spend ceiling for the verifier loop (cap minus the report reserve)."""
        return self.budget.cap_units - self.reserve_units

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FrameworkConfig:
        """Build from a dict, migrating older schema versions transparently."""
        migrated = migrate_config(dict(data))
        migrated.pop("version", None)
        sections = {
            "budget": BudgetConfig,
            "loop": LoopConfig,
            "calibration": CalibrationConfig,
            "logging": LoggingConfig,
            "sanitizer": SanitizerConfig,
            "golden": GoldenConfig,
            "recalibration": RecalibrationConfig,
        }
        kwargs: dict[str, Any] = {}
        for key, klass in sections.items():
            if key in migrated:
                raw = migrated.pop(key)
                if raw is not None:
                    try:
                        kwargs[key] = klass(**raw)
                    except TypeError as exc:
                        raise ConfigError(f"invalid config section {key!r}: {exc}") from exc
        if migrated:  # unknown keys are a config error, not silently ignored
            raise ConfigError(f"unknown config keys: {sorted(migrated)}")
        return cls(**kwargs)
