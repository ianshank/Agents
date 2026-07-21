"""Logging helpers local to the experiment.

Deliberately a small copy of the repo's two established idioms rather than an import:
``scripts/_cli.py`` is not an installable package, and depending on ``agent_core`` only
for logging would couple the harness-independent L1 layer to the wider repo (R1).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

LOG_FORMAT = "%(levelname)-8s %(name)s: %(message)s"


def configure_logging(verbose: bool = False, *, level: int | None = None, fmt: str = LOG_FORMAT) -> None:
    """Configure root logging once for a CLI entry point (scripts/_cli.py pattern)."""
    resolved = level if level is not None else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=resolved, format=fmt, force=True)


def get_logger(name: str) -> logging.Logger:
    """Module-level logger accessor, mirroring agent_core.logging_util.get_logger."""
    return logging.getLogger(name)


@contextmanager
def debug_span(logger: logging.Logger, label: str, **fields: object) -> Iterator[None]:
    """Greppable ENTER/EXIT span with elapsed_ms (agent_core.logging_util.debug_span pattern)."""
    rendered = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    logger.debug("ENTER %s %s", label, rendered)
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.debug("EXIT %s elapsed_ms=%.1f %s", label, elapsed_ms, rendered)
