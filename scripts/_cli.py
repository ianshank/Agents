#!/usr/bin/env python3
"""Shared CLI helpers for the standalone tooling under ``scripts/``.

These modules are run as ``python scripts/<tool>.py`` (and imported flat in tests,
since ``scripts/`` is on ``sys.path``), so this stays dependency-free and importable
both ways. The goal is a single definition of the logging convention every tool used
to copy verbatim.
"""

from __future__ import annotations

import logging

# Single source of truth for the tooling log format. Tools previously duplicated this
# string; centralising it keeps CLI output uniform across the whole scripts/ surface.
LOG_FORMAT: str = "%(levelname)-8s %(name)s: %(message)s"


def configure_logging(verbose: bool = False, *, level: int | None = None, fmt: str = LOG_FORMAT) -> None:
    """Configure root logging for a CLI entrypoint.

    Args:
        verbose: When True (and ``level`` is not given) emit DEBUG, else INFO.
        level: Explicit level that overrides ``verbose`` — pass e.g. ``logging.INFO``
            for tools that don't expose a ``--verbose`` flag.
        fmt: Log line format; defaults to the shared :data:`LOG_FORMAT`.
    """
    resolved = level if level is not None else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=resolved, format=fmt)
