#!/usr/bin/env python3
"""Sentinel supervisor for E2E driver parity and matrix coverage completeness.

Verifies:
  - tests/test_matrix_coverage.py --check
  - pytest tests/test_e2e_driver_parity.py

Usage:
  python skills/e2e-matrix-sentinel/scripts/sentinel.py --check
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / "pyproject.toml").is_file() and (cur / "architecture.yaml").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError(f"Could not locate repo root from {start}")


def check_offline_restamp_report(repo_root: Path) -> int:
    """Verify that any active e2e-report adheres to OfflineRestampConfig (Tiers D/E NOT-RUN)."""
    report_dir = repo_root / "artifacts" / "e2e-report"
    summary_path = report_dir / "summary.json"
    if not summary_path.is_file():
        logger.info("Offline restamp report check: no active e2e-report to audit (OK).")
        return 0

    try:
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from tests import _e2e_matrix as em

        sheets, _ = em.build_sheets_from_report(report_dir)
        problems = em.restamp_source_problems(sheets)
        if problems:
            logger.error("Offline restamping invariant violated in %s:\n%s", report_dir, "\n".join(problems))
            return 1
        logger.info("Offline restamp report check: active e2e-report complies with OfflineRestampConfig.")
        return 0
    except Exception as exc:
        logger.error("Offline restamp report check failed: %s", exc)
        return 1


def run_sentinel(repo_root: Path) -> int:
    steps: list[tuple[str, list[str]]] = [
        ("Matrix Coverage Check", [sys.executable, str(repo_root / "tests" / "test_matrix_coverage.py"), "--check"]),
        (
            "E2E Driver Parity Tests",
            [sys.executable, "-m", "pytest", str(repo_root / "tests" / "test_e2e_driver_parity.py"), "-q"],
        ),
        (
            "Offline Restamping Invariant Unit Tests",
            [
                sys.executable,
                "-m",
                "pytest",
                str(repo_root / "tests" / "test_e2e_matrix.py"),
                "-k",
                "restamp_source_problems",
                "-q",
            ],
        ),
    ]

    restamp_rc = check_offline_restamp_report(repo_root)
    if restamp_rc != 0:
        return restamp_rc

    for name, cmd in steps:
        logger.info("Running %s...", name)
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error("%s FAILED (exit %d):\n%s\n%s", name, proc.returncode, proc.stdout, proc.stderr)
            return proc.returncode
        logger.info("%s PASSED.", name)

    logger.info("All E2E matrix and driver parity checks PASSED.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", default=True, help="Run all verification gates")
    parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repo_root = _find_repo_root(Path(__file__))
    return run_sentinel(repo_root)


if __name__ == "__main__":
    sys.exit(main())
