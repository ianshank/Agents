#!/usr/bin/env python3
"""Validation script for Feature F-007: Eval-integrity protected-path guard.

Runs the matcher + CI-guard meta-suite (every protected glob blocked, implementation
modules allowed, label parsing, and the guard's block/allow CLI decisions).

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
"""

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


def main() -> int:
    configure_logging()
    project_root = Path(__file__).resolve().parent.parent.parent
    test_file = project_root / "tests" / "test_protected_paths.py"
    if not test_file.is_file():
        logger.error("FAIL: %s not found", test_file)
        return 1

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    ok = run_subprocess_check(cmd, cwd=project_root, timeout=300, label="F-007 validation")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
