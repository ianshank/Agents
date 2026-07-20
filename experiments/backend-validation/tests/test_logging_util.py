"""Unit tests for the local logging helpers."""

from __future__ import annotations

import logging

import pytest

from backend_validation.logging_util import configure_logging, debug_span, get_logger


def test_configure_logging_levels() -> None:
    configure_logging(verbose=True)
    assert logging.getLogger().level == logging.DEBUG
    configure_logging(verbose=False)
    assert logging.getLogger().level == logging.INFO
    configure_logging(level=logging.WARNING)
    assert logging.getLogger().level == logging.WARNING


def test_debug_span_emits_enter_and_exit_with_fields(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("bv.test")
    with caplog.at_level(logging.DEBUG, logger="bv.test"), debug_span(logger, "phase", backend="opik"):
        logger.debug("inside")
    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("ENTER phase backend=opik") for message in messages)
    assert any("EXIT phase elapsed_ms=" in message and "backend=opik" in message for message in messages)


def test_debug_span_exits_on_exception(caplog: pytest.LogCaptureFixture) -> None:
    logger = get_logger("bv.test2")
    try:
        with caplog.at_level(logging.DEBUG, logger="bv.test2"), debug_span(logger, "boom"):
            raise ValueError("x")
    except ValueError:
        pass
    assert any("EXIT boom" in record.getMessage() for record in caplog.records)
