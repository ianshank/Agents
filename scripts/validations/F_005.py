#!/usr/bin/env python3
"""Validation script for Feature F-005: Langfuse Tracing Integration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import configure_logging, run_subprocess_check

logger = logging.getLogger(__name__)


def validate_f005() -> bool:
    project_root = Path(__file__).resolve().parent.parent.parent
    test_file = project_root / "tests" / "test_langfuse_integration.py"

    if not test_file.is_file():
        logger.error("FAIL: test_langfuse_integration.py not found at %s", test_file)
        return False

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-v"]
    return run_subprocess_check(cmd, cwd=project_root, timeout=60, label="F-005 validation")


def main() -> int:
    configure_logging()
    return 0 if validate_f005() else 1


if __name__ == "__main__":
    sys.exit(main())
