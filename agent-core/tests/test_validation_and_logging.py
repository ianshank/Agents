import logging

import pytest

from agent_core import (
    BudgetLedger,
    FrameworkConfig,
    IsotonicCalibrator,
    brier_score,
    configure_logging,
    debug_span,
    evaluate_calibration,
    expected_calibration_error,
    get_logger,
    reliability_bins,
)


# --- calibration input validation -------------------------------------------
def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        brier_score([0.1, 0.2], [1])


def test_empty_input_raises():
    with pytest.raises(ValueError):
        expected_calibration_error([], [], n_bins=5)


def test_probability_out_of_range_raises():
    with pytest.raises(ValueError):
        brier_score([1.2], [1])


def test_bad_outcome_label_raises():
    with pytest.raises(ValueError):
        brier_score([0.5], [2])


def test_reliability_bins_rejects_zero_bins():
    with pytest.raises(ValueError):
        reliability_bins([0.5], [1], n_bins=0)


def test_sparse_bins_have_zero_count_entries():
    bins = reliability_bins([0.05, 0.95], [0, 1], n_bins=10)
    assert any(b.count == 0 for b in bins)  # empty middle bins are represented


def test_isotonic_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        IsotonicCalibrator().predict(0.5)


def test_evaluate_calibration_single_class_auroc_is_none():
    report = evaluate_calibration(
        [0.6, 0.7], [1, 1], n_bins=10, ece_target=1.0, mce_target=1.0, auroc_target=0.8
    )
    assert report.auroc is None  # discrimination undefined, not a crash


# --- budget overspend clamp --------------------------------------------------
def test_remaining_for_loop_clamps_at_zero():
    cfg = FrameworkConfig.from_dict({"budget": {"cap_units": 100.0, "reserve_fraction": 0.2}})
    led = BudgetLedger(cfg)
    led.record(95.0)  # ceiling is 80; overspent relative to loop ceiling
    assert led.remaining_for_loop == 0.0


# --- logging -----------------------------------------------------------------
def test_configure_logging_rejects_unknown_level():
    with pytest.raises(ValueError):
        configure_logging(level="NOPE")


def test_get_logger_rejects_unknown_level():
    with pytest.raises(ValueError):
        get_logger("x", level="NOPE")


def test_debug_span_executes_block():
    logger = get_logger("agent_core.test", level="DEBUG")
    logger.setLevel(logging.DEBUG)
    ran = []
    with debug_span(logger, "unit", k=1):
        ran.append(True)
    assert ran == [True]
