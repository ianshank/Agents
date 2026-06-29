#!/usr/bin/env python3
"""Tests for the shared CLI logging helper (``scripts/_cli.py``).

We assert on the arguments passed to ``logging.basicConfig`` rather than the resulting
root-logger state, because ``basicConfig`` is a no-op once handlers exist (pytest's own
logging plugin installs one), which would make state-based assertions flaky.
"""

from __future__ import annotations

import logging
from typing import Any

import _cli
import pytest


@pytest.fixture
def captured_basic_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kw: calls.update(kw))
    return calls


def test_default_is_info(captured_basic_config: dict[str, Any]) -> None:
    _cli.configure_logging()
    assert captured_basic_config["level"] == logging.INFO
    assert captured_basic_config["format"] == _cli.LOG_FORMAT


def test_verbose_sets_debug(captured_basic_config: dict[str, Any]) -> None:
    _cli.configure_logging(verbose=True)
    assert captured_basic_config["level"] == logging.DEBUG


def test_explicit_level_overrides_verbose(captured_basic_config: dict[str, Any]) -> None:
    _cli.configure_logging(verbose=True, level=logging.WARNING)
    assert captured_basic_config["level"] == logging.WARNING


def test_custom_format(captured_basic_config: dict[str, Any]) -> None:
    _cli.configure_logging(fmt="%(message)s")
    assert captured_basic_config["format"] == "%(message)s"
