#!/usr/bin/env python3
"""Unified Tier A Mechanical Verification Gate.

Executes all deterministic, offline mechanical checks without side effects:
- Charter invariants and reference drift
- ADR 0019 file size budgets
- Guard reachability filters
- Ruff format and lint checks
- Matrix coverage freshness
- Frozen synthetic corpora integrity (RCA, Requirements, TestGen)
- Fast feature validation suite (scripts/validate.py --tier fast)

Exit code:
  0 - All mechanical gates passed
  1 - One or more gates failed
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify_tier_a")


def run_gate(name: str, cmd: list[str]) -> bool:
    logger.info("Running Gate [%s]: %s", name, " ".join(cmd))
    start_time = time.monotonic()
    env = os.environ.copy()
    src_dir = str(REPO_ROOT / "src")
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_dir

    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - start_time
    if proc.returncode == 0:
        logger.info("[PASS] %s (%.2fs)", name, elapsed)
        return True
    else:
        logger.error("[FAIL] %s (exit %d in %.2fs)", name, proc.returncode, elapsed)
        if proc.stdout.strip():
            logger.error("STDOUT:\n%s", proc.stdout.strip())
        if proc.stderr.strip():
            logger.error("STDERR:\n%s", proc.stderr.strip())
        return False


def main() -> int:
    venv_py = (
        REPO_ROOT
        / ".venv"
        / ("Scripts" if sys.platform == "win32" else "bin")
        / ("python.exe" if sys.platform == "win32" else "python")
    )
    py = str(venv_py) if venv_py.exists() else sys.executable
    gates = [
        ("Charter Invariants", [py, "scripts/check_charter_invariants.py"]),
        ("Charter Drift", [py, "scripts/check_charter_drift.py"]),
        ("Size Budget", [py, "scripts/check_size_budget.py"]),
        ("Guard Reachability", [py, "scripts/check_guard_reachability.py"]),
        ("Ruff Format Check", [py, "-m", "ruff", "format", "--check", "."]),
        ("Ruff Lint Check", [py, "-m", "ruff", "check", "."]),
        ("Matrix Coverage", [py, "tests/test_matrix_coverage.py", "--check"]),
        ("RCA Corpus Freshness", [py, "scripts/gen_rca_corpus.py", "--check"]),
        ("Requirements Corpus Freshness", [py, "scripts/gen_requirements_corpus.py", "--check"]),
        ("TestGen Corpus Freshness", [py, "scripts/gen_testgen_corpus.py", "--check"]),
        ("Fast Feature Validators", [py, "scripts/validate.py", "--tier", "fast"]),
    ]

    failed = []
    for name, cmd in gates:
        if not run_gate(name, cmd):
            failed.append(name)

    if failed:
        logger.error("=== Tier A Verification FAILED (%d failures) ===", len(failed))
        for f in failed:
            logger.error("  - %s", f)
        return 1

    logger.info("=== Tier A Verification PASSED (All %d gates green) ===", len(gates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
