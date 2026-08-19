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
    ProbeConfig,
    RecalibrationConfig,
    SanitizerConfig,
)
from .golden import (
    GoldenItem,
    GoldenSet,
    GoldenSplit,
    cohen_kappa,
    evaluate_on_split,
    percent_agreement,
    split,
)
from .judge_calibration import (
    OrderProbeResult,
    PairOutcome,
    SelfPreferenceResult,
    VerbosityProbeResult,
    order_flip_rate,
    self_preference_breakdown,
    verbosity_preference_delta,
)
from .judge_calibration_report import (
    REPORT_SCHEMA_VERSION,
    JudgeCalibrationReport,
    build_judge_calibration_report,
)
from .logging_util import configure_logging, debug_span, get_logger
from .loop import LoopController, RunResult
from .pairwise import PairwiseItem, PairwiseSet
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
from .ppi import (
    CorrelationConfig,
    PPIConfig,
    PPIEstimate,
    effective_n_multiplier,
    pearson_r,
    ppi_plus_interval,
)
from .protocols import (
    AsyncCycleRunner,
    Clock,
    CostEstimator,
    CycleResult,
    CycleRunner,
    CycleState,
    FixedClock,
    StopOutcome,
    StopReason,
    SystemClock,
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
    "REPORT_SCHEMA_VERSION",
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
    "Clock",
    "ConfigError",
    "ConvergenceCondition",
    "CorrelationConfig",
    "CostEstimator",
    "CycleResult",
    "CycleRunner",
    "CycleState",
    "Finding",
    "FixedClock",
    "FrameworkConfig",
    "Gate",
    "GoldenConfig",
    "GoldenItem",
    "GoldenSet",
    "GoldenSplit",
    "IsotonicCalibrator",
    "JudgeCalibrationReport",
    "LoggingConfig",
    "LoopConfig",
    "LoopController",
    "MaxCyclesCondition",
    "NoProgressCondition",
    "OrderProbeResult",
    "PPIConfig",
    "PPIEstimate",
    "PairOutcome",
    "PairwiseItem",
    "PairwiseSet",
    "ParallelClaimRunner",
    "ProbeConfig",
    "RecalibrationConfig",
    "RuleSanitizer",
    "RunResult",
    "SanitizationResult",
    "SanitizationRule",
    "Sanitizer",
    "SanitizerConfig",
    "SelfPreferenceResult",
    "StopOutcome",
    "StopReason",
    "SystemClock",
    "TemperatureScaler",
    "VerbosityProbeResult",
    "__version__",
    "auroc",
    "brier_decomposition",
    "brier_score",
    "build_judge_calibration_report",
    "build_sanitized_claims",
    "calibrator_from_dict",
    "calibrator_to_dict",
    "cohen_kappa",
    "configure_logging",
    "cycle_state_from_dict",
    "cycle_state_to_dict",
    "debug_span",
    "ece",
    "effective_n_multiplier",
    "evaluate_calibration",
    "evaluate_on_split",
    "expected_calibration_error",
    "get_logger",
    "load_run",
    "make_calibrator",
    "maximum_calibration_error",
    "order_flip_rate",
    "pearson_r",
    "percent_agreement",
    "ppi_plus_interval",
    "reliability_bins",
    "run_result_from_dict",
    "run_result_to_dict",
    "save_run",
    "selective_risk_coverage",
    "self_preference_breakdown",
    "split",
    "verbosity_preference_delta",
    "wilson_interval",
]
