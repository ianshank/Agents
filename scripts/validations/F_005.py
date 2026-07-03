#!/usr/bin/env python3
"""Validation script for Feature F-005: Langfuse Tracing Integration."""

import os
import subprocess
import sys


def validate_f005() -> bool:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    test_file = os.path.join(project_root, "tests", "test_langfuse_integration.py")

    if not os.path.isfile(test_file):
        print(f"FAIL: test_langfuse_integration.py not found at {test_file}")
        return False

    cmd = [sys.executable, "-m", "pytest", test_file, "-v"]

    print(f"Running command: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        print("STDOUT:")
        print(res.stdout)
        print("STDERR:")
        print(res.stderr)

        if res.returncode == 0:
            print("OK: F-005 validation passed.")
            return True
        else:
            print(f"FAIL: pytest exited with code {res.returncode}")
            return False
    except Exception as e:
        print(f"FAIL: Validation script crashed: {e}")
        return False


if __name__ == "__main__":
    if not validate_f005():
        sys.exit(1)
    sys.exit(0)
