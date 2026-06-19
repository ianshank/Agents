#!/usr/bin/env python3
"""Validation script for Feature F-008: Agentic auto-fix loop (design-only, disabled).

Runs the inert loop's safety meta-suite (disabled by default, scope guard rejects every
protected glob, escalation at max_cycles, verdict from clean re-evaluation).

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
    test_file = project_root / "tests" / "test_fix_loop.py"
    if not test_file.is_file():
        print(f"FAIL: {test_file} not found")
        return 1

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, timeout=300)
    print(result.stdout)
    print(result.stderr)
    if result.returncode != 0:
        print(f"FAIL: pytest exited with {result.returncode}")
        return 1
    print("OK: F-008 validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
