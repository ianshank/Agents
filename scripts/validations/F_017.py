#!/usr/bin/env python3
"""Validation script for F-017 – Dynamic Versioning.

Checks:
    1. ``version.py`` uses importlib.metadata (no hardcoded version string).
    2. ``__version__`` is importable and non-empty.
    3. ``SCHEMA_VERSION`` is importable and equals ``"1.0"``.
    4. ``_DIST_NAME`` matches the distribution name in ``pyproject.toml``.
    5. ``__init__.py`` re-exports ``__version__`` and ``SCHEMA_VERSION``.

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Resolve the project root (two levels up from this script)."""
    return Path(__file__).resolve().parent.parent.parent


def _check(condition: bool, msg: str, errors: List[str]) -> bool:
    """Log and track a check result."""
    if not condition:
        errors.append(msg)
        logger.error("FAIL: %s", msg)
        return False
    logger.info("OK: %s", msg)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all F-017 validation checks."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    root = _project_root()
    errors: List[str] = []

    # 1. version.py uses importlib.metadata, not a hardcoded string
    version_path = root / "src" / "eval_harness" / "version.py"
    if not version_path.exists():
        errors.append("Missing: src/eval_harness/version.py")
        logger.error("Missing: src/eval_harness/version.py")
    else:
        src = version_path.read_text(encoding="utf-8")
        _check(
            "importlib.metadata" in src,
            "version.py uses importlib.metadata",
            errors,
        )
        # Ensure the old hardcoded pattern is gone
        # Match lines like: __version__ = "1.0.0"  (hardcoded literal)
        hardcoded = re.search(r'^__version__\s*=\s*["\'][\d.]+["\']', src, re.MULTILINE)
        _check(
            hardcoded is None,
            "version.py does not contain a hardcoded __version__ literal",
            errors,
        )

    # 2. __version__ is importable and non-empty
    try:
        from eval_harness.version import __version__
        _check(
            isinstance(__version__, str) and len(__version__) > 0,
            "__version__ is a non-empty string: %s" % __version__,
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import __version__: %s" % exc)
        logger.error("Cannot import __version__: %s", exc)

    # 3. SCHEMA_VERSION equals "1.0"
    try:
        from eval_harness.version import SCHEMA_VERSION
        _check(
            SCHEMA_VERSION == "1.0",
            "SCHEMA_VERSION == '1.0'",
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import SCHEMA_VERSION: %s" % exc)
        logger.error("Cannot import SCHEMA_VERSION: %s", exc)

    # 4. _DIST_NAME matches pyproject.toml
    try:
        from eval_harness.version import _DIST_NAME
        _check(
            _DIST_NAME == "langfuse-eval-harness",
            "_DIST_NAME == 'langfuse-eval-harness'",
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import _DIST_NAME: %s" % exc)
        logger.error("Cannot import _DIST_NAME: %s", exc)

    # 5. __init__.py re-exports both symbols
    try:
        from eval_harness import __version__ as pkg_v, SCHEMA_VERSION as pkg_sv
        _check(
            pkg_v == __version__,
            "eval_harness.__version__ matches version.__version__",
            errors,
        )
        _check(
            pkg_sv == SCHEMA_VERSION,
            "eval_harness.SCHEMA_VERSION matches version.SCHEMA_VERSION",
            errors,
        )
    except ImportError as exc:
        errors.append("Cannot import from eval_harness: %s" % exc)
        logger.error("Cannot import from eval_harness: %s", exc)

    # Summary
    if errors:
        logger.error("F-017 FAILED with %d error(s):", len(errors))
        for err in errors:
            logger.error("  • %s", err)
        return 1

    logger.info("F-017 passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
