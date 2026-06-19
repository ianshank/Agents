"""Tests for the vendored logging helpers."""
from __future__ import annotations

import logging

import pytest
from adguard.logging_util import configure_logging, debug_span, get_logger


def test_configure_logging_sets_level():
    configure_logging(level="DEBUG", force=True)
    assert logging.getLogger().level == logging.DEBUG
    # restore to a quieter default for other tests
    configure_logging(level="WARNING", force=True)


def test_configure_logging_rejects_unknown_level():
    with pytest.raises(ValueError, match="unknown log level"):
        configure_logging(level="NOPE")


def test_get_logger_overrides_level():
    logger = get_logger("adguard.test.override", level="ERROR")
    assert logger.level == logging.ERROR


def test_get_logger_rejects_unknown_level():
    with pytest.raises(ValueError, match="unknown log level"):
        get_logger("adguard.test.bad", level="WAT")


def test_get_logger_without_level_leaves_it_unset():
    logger = get_logger("adguard.test.noset")
    assert logger.name == "adguard.test.noset"


def test_debug_span_emits_enter_and_exit(caplog):
    logger = get_logger("adguard.test.span", level="DEBUG")
    with caplog.at_level(logging.DEBUG, logger="adguard.test.span"), debug_span(logger, "work", n=3):
        pass
    messages = [r.getMessage() for r in caplog.records]
    assert any("ENTER work" in m for m in messages)
    assert any("EXIT  work" in m and "elapsed_ms=" in m for m in messages)
