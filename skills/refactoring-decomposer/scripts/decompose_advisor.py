#!/usr/bin/env python3
"""Decomposition advisor: identifies functions and files exceeding structural budgets.

Wraps scripts/check_size_budget.py with actionable decomposition recommendations.

Usage:
  python skills/refactoring-decomposer/scripts/decompose_advisor.py --scan
  python skills/refactoring-decomposer/scripts/decompose_advisor.py --scan --root src/eval_harness
"""

from __future__ import annotations

import argparse
import json
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


def scan_size_budgets(repo_root: Path, roots: list[str] | None = None) -> int:
    cmd = [sys.executable, str(repo_root / "scripts" / "check_size_budget.py"), "--json"]
    if roots:
        for r in roots:
            cmd.extend(["--root", r])

    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        logger.error("check_size_budget.py execution failed:\n%s", proc.stderr)
        return proc.returncode

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse check_size_budget.py output as JSON: %s", exc)
        return 1

    if not isinstance(report, list):
        logger.error("Expected report to be a JSON list, got: %s", type(report).__name__)
        return 1

    hard_findings = [f for f in report if f.get("hard")]
    func_warnings = [f for f in report if not f.get("hard") and f.get("kind") == "function_lines"]
    method_warnings = [f for f in report if not f.get("hard") and f.get("kind") == "public_methods"]

    print("=== Decomposition Advisor Report ===")
    print(f"Hard file-budget violations (>500 lines): {len(hard_findings)}")
    print(f"Function-length warnings (>50 lines): {len(func_warnings)}")
    print(f"Class public-method warnings (>20 methods): {len(method_warnings)}")

    if hard_findings:
        print("\nCRITICAL - The following files MUST be decomposed immediately:")
        for f in hard_findings:
            print(f"  - {f['path']} ({f['value']} lines > {f['limit']})")

    top_func_warnings = sorted(func_warnings, key=lambda x: x["value"], reverse=True)[:10]
    if top_func_warnings:
        print("\nTop Over-Budget Functions for Decomposition:")
        for w in top_func_warnings:
            print(f"  - {w['path']}::{w['name']} ({w['value']} lines > {w['limit']})")

    top_method_warnings = sorted(method_warnings, key=lambda x: x["value"], reverse=True)[:10]
    if top_method_warnings:
        print("\nTop Over-Budget Classes (Public Methods) for Decomposition:")
        for w in top_method_warnings:
            print(f"  - {w['path']}::{w['name']} ({w['value']} methods > {w['limit']})")

    return 1 if hard_findings else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", default=True, help="Scan source files for budget findings")
    parser.add_argument("--root", action="append", help="Limit analysis to specific directory roots")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repo_root = _find_repo_root(Path(__file__))
    return scan_size_budgets(repo_root, roots=args.root)


if __name__ == "__main__":
    sys.exit(main())
