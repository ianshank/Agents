"""Shared types for the calibration report: config, row/view records, estimator names.

A neutral layer both the analysis (:mod:`agent_core.calibration_report`) and the
presentation (:mod:`agent_core.calibration_report_render`) depend on, so neither has to
import the other. Splitting them was forced by the repo's 500-line file budget; keeping
the types here is what makes the split acyclic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import ConfigError
from .ppi import PPIEstimate

# Interval estimators this report can render. Single-sourced so the CLI choices, the
# config validator, and the renderer cannot drift apart.
WILSON = "wilson"
PPI_PLUS = "ppi++"
ESTIMATORS = (WILSON, PPI_PLUS)


@dataclass(frozen=True)
class ReportConfig:
    """Calibration-report knobs — documented defaults, not magic numbers at call sites."""

    n_bins: int = 10
    risk_target: float = 0.05  # abstention risk target for the selective-risk summary
    z: float = 1.96  # Wilson-interval z (95% by default)
    # Interval estimator for the base rate. "wilson" is the default and the only estimator
    # the *gate* uses; "ppi++" additionally reports a power-tuned prediction-powered
    # interval that borrows strength from unaudited records. Both are always rendered when
    # ppi++ is selected -- a single number would hide which estimator produced it.
    estimator: str = "wilson"

    def __post_init__(self) -> None:
        # Messages name the offending value (repo convention: `require_exact_keys`/`parse_shas_file`
        # both echo what they got). `math.isfinite` guards rule out NaN/inf, which would otherwise
        # slip past the range checks (e.g. `z=inf` passes `z > 0`) and produce a maximally-wide CI.
        if self.n_bins < 1:
            raise ConfigError(f"calibration-report.n_bins must be >= 1 (got {self.n_bins!r})")
        if not (math.isfinite(self.risk_target) and 0.0 <= self.risk_target <= 1.0):
            raise ConfigError(
                "calibration-report.risk_target must be a finite value in [0, 1] "
                f"(got {self.risk_target!r})"
            )
        if not (math.isfinite(self.z) and self.z > 0):
            raise ConfigError(f"calibration-report.z must be a finite value > 0 (got {self.z!r})")
        if self.estimator not in ESTIMATORS:
            raise ConfigError(
                f"calibration-report.estimator must be one of {sorted(ESTIMATORS)} "
                f"(got {self.estimator!r})"
            )


@dataclass(frozen=True)
class SliceReport:
    label: str
    n: int
    n_correct: int
    base_rate: float | None
    base_rate_ci: tuple[float, float] | None
    ece: float | None
    brier: float | None
    reliability: float | None
    resolution: float | None
    uncertainty: float | None
    auroc: float | None
    abstention_at_target: float | None
    risk_target: float
    degenerate: str | None
    # Populated only when ``ReportConfig.estimator == "ppi++"``. Defaulted so every
    # existing construction and unpacking of this record keeps working unchanged.
    ppi: PPIEstimate | None = None


@dataclass(frozen=True)
class View:
    name: str
    tau_eligible: bool
    slices: list[SliceReport]


@dataclass(frozen=True)
class ReportDoc:
    domain_filter: str
    total_records: int
    resolved_records: int
    by_label_source: dict[str, int]
    views: list[View]
    # Which interval estimator produced the intervals below. Defaulted so existing
    # constructions of this document keep working.
    estimator: str = WILSON
