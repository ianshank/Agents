#!/usr/bin/env python3
"""Validation script for Feature F-006: Regression gate (net-new failures vs HEAD).

Exercises the gate's verification criteria by running its offline, deterministic
meta-suite (worktree baseline isolation, net-new diff correctness, class-based
nodeid reconstruction, line-keyed lint identity, report schema conformance).

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
    test_file = project_root / "tests" / "test_regression_gate.py"
    if not test_file.is_file():
        logger.error("FAIL: %s not found", test_file)
        return 1

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    ok = run_subprocess_check(cmd, cwd=project_root, timeout=600, label="F-006 validation")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
