#!/usr/bin/env python3
"""Validation script for F-002 – OpenAI-compatible LLM judge.

Delegates to pytest, running the ``tests/test_openai_judge.py`` test module.
Exits with pytest's own exit code so the harness can interpret the result.

Exit codes:
    0 – all tests passed
    non-zero – pytest failure or error
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_MODULE: str = "tests/test_openai_judge.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Resolve the project root (two levels up from this script)."""
    return Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run pytest for the OpenAI judge tests and return the exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    root = _project_root()
    test_path = root / TEST_MODULE

    if not test_path.exists():
        logger.error("Test module not found: %s", test_path)
        return 1

    cmd = [sys.executable, "-m", "pytest", str(test_path), "-q"]
    logger.info("Running: %s", " ".join(cmd))

    result = subprocess.run(cmd, cwd=str(root))

    if result.returncode == 0:
        logger.info("F-002 passed ✓")
    else:
        logger.error("F-002 FAILED (pytest exit code %d)", result.returncode)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
