"""Shared helpers for the per-feature validation scripts (F_0XX).

Single-sources the logging convention and the pass/fail check that every
validator used to duplicate verbatim. Importable both standalone
(``python scripts/validations/F_0XX.py`` puts this directory on ``sys.path``)
and under pytest, after ensuring the repo ``scripts/`` directory is importable
so the canonical ``_cli.configure_logging`` can be reused.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from _cli import configure_logging  # noqa: E402  re-exported for the validators

__all__ = ["check", "configure_logging", "report"]

_logger = logging.getLogger("validations")


def check(condition: bool, msg: str, errors: list[str]) -> bool:
    """Record a single validation check: append + log on failure, log on success."""
    if not condition:
        errors.append(msg)
        _logger.error("FAIL: %s", msg)
        return False
    _logger.info("OK: %s", msg)
    return True


def report(logger: logging.Logger, label: str, errors: list[str]) -> int:
    """Emit the standard pass/fail summary and return the process exit code."""
    if errors:
        logger.error("%s FAILED with %d error(s):", label, len(errors))
        for err in errors:
            logger.error("  - %s", err)
        return 1
    logger.info("%s passed", label)
    return 0
