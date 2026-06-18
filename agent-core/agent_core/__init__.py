"""agent_core — deterministic control & calibration core for a research-assessment agent.

Public API is intentionally small and stable. I/O-bound nodes (verifier,
retrieval, LLM) are injected via the Protocols in ``agent_core.protocols``.
"""
from __future__ import annotations

import logging

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
    BudgetConfig,
    CalibrationConfig,
    ConfigError,
    FrameworkConfig,
    LoggingConfig,
    LoopConfig,
)
from .logging_util import configure_logging, debug_span, get_logger
from .loop import LoopController, RunResult
from .protocols import (
    CostEstimator,
    CycleResult,
    CycleRunner,
    CycleState,
    StopOutcome,
    StopReason,
)
from .stop import (
    BudgetCondition,
    ConvergenceCondition,
    Gate,
    MaxCyclesCondition,
    NoProgressCondition,
)
from .version import SCHEMA_VERSION, deprecated_alias

__version__ = SCHEMA_VERSION

# Library best practice: attach a NullHandler so importing apps control logging.
logging.getLogger("agent_core").addHandler(logging.NullHandler())

# --- backwards-compat shim ---------------------------------------------------
# ``ece`` was the public name before 1.1.0; keep it working with a warning.
ece = deprecated_alias("expected_calibration_error")(expected_calibration_error)

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "FrameworkConfig",
    "BudgetConfig",
    "LoopConfig",
    "CalibrationConfig",
    "LoggingConfig",
    "ConfigError",
    "BudgetLedger",
    "BudgetExceededError",
    "LoopController",
    "RunResult",
    "Gate",
    "MaxCyclesCondition",
    "BudgetCondition",
    "ConvergenceCondition",
    "NoProgressCondition",
    "CycleState",
    "CycleResult",
    "CycleRunner",
    "CostEstimator",
    "StopReason",
    "StopOutcome",
    "reliability_bins",
    "Bin",
    "wilson_interval",
    "expected_calibration_error",
    "maximum_calibration_error",
    "brier_score",
    "brier_decomposition",
    "BrierDecomposition",
    "auroc",
    "selective_risk_coverage",
    "Calibrator",
    "IsotonicCalibrator",
    "CalibrationReport",
    "evaluate_calibration",
    "configure_logging",
    "get_logger",
    "debug_span",
    "ece",
]
