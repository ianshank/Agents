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

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent.parent
    test_file = project_root / "tests" / "test_regression_gate.py"
    if not test_file.is_file():
        print(f"FAIL: {test_file} not found")
        return 1

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=600)
    print(result.stdout)
    print(result.stderr)
    if result.returncode != 0:
        print(f"FAIL: pytest exited with {result.returncode}")
        return 1
    print("OK: F-006 validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
