"""agent_core — deterministic control & calibration core for a research-assessment agent.

Public API is intentionally small and stable. I/O-bound nodes (verifier,
retrieval, LLM) are injected via the Protocols in ``agent_core.protocols``.
"""

from __future__ import annotations

import logging

from .async_loop import AsyncLoopController, ParallelClaimRunner
from .budget import BudgetExceededError, BudgetLedger
from .calibration import (
    Bin,
    BrierDecomposition,
    CalibrationReport,
    Calibrator,
    IsotonicCalibrator,
    auroc,
    brier_decomposition,
    brier_score,
    evaluate_calibration,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_bins,
    selective_risk_coverage,
    wilson_interval,
)
from .config import (
    AsyncConfig,
    BudgetConfig,
    CalibrationConfig,
    ConfigError,
    FrameworkConfig,
    GoldenConfig,
    LoggingConfig,
    LoopConfig,
    RecalibrationConfig,
    SanitizerConfig,
)
from .golden import (
    GoldenItem,
    GoldenSet,
    GoldenSplit,
    cohen_kappa,
    evaluate_on_split,
    split,
)
from .logging_util import configure_logging, debug_span, get_logger
from .loop import LoopController, RunResult
from .persistence import (
    RUN_STATE_SCHEMA_VERSION,
    calibrator_from_dict,
    calibrator_to_dict,
    cycle_state_from_dict,
    cycle_state_to_dict,
    load_run,
    run_result_from_dict,
    run_result_to_dict,
    save_run,
)
from .protocols import (
    AsyncCycleRunner,
    CostEstimator,
    CycleResult,
    CycleRunner,
    CycleState,
    StopOutcome,
    StopReason,
)
from .recalibration import (
    CALIBRATOR_FACTORIES,
    CalibratorRegistry,
    TemperatureScaler,
    make_calibrator,
)
from .sanitize import (
    Finding,
    RuleSanitizer,
    SanitizationResult,
    SanitizationRule,
    Sanitizer,
    build_sanitized_claims,
)
from .stop import (
    BudgetCondition,
    ConvergenceCondition,
    Gate,
    MaxCyclesCondition,
    NoProgressCondition,
)
from .version import SCHEMA_VERSION, __version__, deprecated_alias

# Library best practice: attach a NullHandler so importing apps control logging.
logging.getLogger("agent_core").addHandler(logging.NullHandler())

# --- backwards-compat shim ---------------------------------------------------
# ``ece`` was the public name before 1.1.0; keep it working with a warning.
ece = deprecated_alias("expected_calibration_error", deprecated_name="ece")(
    expected_calibration_error
)

__all__ = [
    "CALIBRATOR_FACTORIES",
    "RUN_STATE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "AsyncConfig",
    "AsyncCycleRunner",
    "AsyncLoopController",
    "Bin",
    "BrierDecomposition",
    "BudgetCondition",
    "BudgetConfig",
    "BudgetExceededError",
    "BudgetLedger",
    "CalibrationConfig",
    "CalibrationReport",
    "Calibrator",
    "CalibratorRegistry",
    "ConfigError",
    "ConvergenceCondition",
    "CostEstimator",
    "CycleResult",
    "CycleRunner",
    "CycleState",
    "Finding",
    "FrameworkConfig",
    "Gate",
    "GoldenConfig",
    "GoldenItem",
    "GoldenSet",
    "GoldenSplit",
    "IsotonicCalibrator",
    "LoggingConfig",
    "LoopConfig",
    "LoopController",
    "MaxCyclesCondition",
    "NoProgressCondition",
    "ParallelClaimRunner",
    "RecalibrationConfig",
    "RuleSanitizer",
    "RunResult",
    "SanitizationResult",
    "SanitizationRule",
    "Sanitizer",
    "SanitizerConfig",
    "StopOutcome",
    "StopReason",
    "TemperatureScaler",
    "__version__",
    "auroc",
    "brier_decomposition",
    "brier_score",
    "build_sanitized_claims",
    "calibrator_from_dict",
    "calibrator_to_dict",
    "cohen_kappa",
    "configure_logging",
    "cycle_state_from_dict",
    "cycle_state_to_dict",
    "debug_span",
    "ece",
    "evaluate_calibration",
    "evaluate_on_split",
    "expected_calibration_error",
    "get_logger",
    "load_run",
    "make_calibrator",
    "maximum_calibration_error",
    "reliability_bins",
    "run_result_from_dict",
    "run_result_to_dict",
    "save_run",
    "selective_risk_coverage",
    "split",
    "wilson_interval",
]
