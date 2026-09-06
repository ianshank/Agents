"""Logging and debugging helpers.

All logging configuration flows from :class:`agent_core.config.LoggingConfig`
so nothing about levels or formatting is hardcoded in business logic. A
``debug_span`` context manager gives uniform, greppable enter/exit traces for
any block worth instrumenting.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator, Mapping

from .config import LoggingConfig

_DEFAULT_FORMAT = LoggingConfig.fmt  # keep the historical kwarg default in lockstep


def configure_logging(
    level: str = LoggingConfig.level,
    fmt: str = _DEFAULT_FORMAT,
    *,
    force: bool = False,
) -> None:
    """Configure the root handler. ``level`` is resolved dynamically by name."""
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):  # unknown level name
        raise ValueError(f"unknown log level: {level!r}")
    logging.basicConfig(level=numeric, format=fmt, force=force)


def configure_from_config(
    config: LoggingConfig | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    force: bool = False,
) -> None:
    """Apply :class:`LoggingConfig`, overlaying ``config.level_env_var`` when set.

    Empty env values are ignored so a GitHub ``vars`` pass-through of an unset
    variable cannot blank the configured level. Call-site ``configure_logging(level=...)``
    remains byte-compatible for tests and scripts that pin a level explicitly.
    """
    cfg = config or LoggingConfig()
    env = os.environ if environ is None else environ
    overlay = env.get(cfg.level_env_var, "").strip()
    configure_logging(level=overlay or cfg.level, fmt=cfg.fmt, force=force)


def get_logger(name: str, level: str | None = None) -> logging.Logger:
    """Return a named logger, optionally overriding its level dynamically."""
    logger = logging.getLogger(name)
    if level is not None:
        numeric = logging.getLevelName(level.upper())
        if not isinstance(numeric, int):
            raise ValueError(f"unknown log level: {level!r}")
        logger.setLevel(numeric)
    return logger


@contextlib.contextmanager
def debug_span(logger: logging.Logger, label: str, **fields: object) -> Iterator[None]:
    """Log entry/exit of a block at DEBUG with elapsed time and structured fields."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.debug("ENTER %s %s", label, extra)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        logger.debug("EXIT  %s elapsed_ms=%.3f", label, elapsed_ms)
