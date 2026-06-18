"""Configuration schema.

Every tunable in the framework lives here as a dataclass field with a documented
default. Business logic reads these values; it never embeds literals. Configs are
versioned and round-trip through ``to_dict``/``from_dict`` with automatic
migration of older payloads, which is what makes persisted configs
backwards-compatible across releases.
"""

from __future__ import annotations

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
class FrameworkConfig:
    version: str = SCHEMA_VERSION
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

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
