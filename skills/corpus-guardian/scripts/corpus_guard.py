#!/usr/bin/env python3
"""Unified supervisor for the four frozen synthetic evaluation corpora.

Checks freshness or triggers regeneration across:
  - RCA Corpus (scripts/gen_rca_corpus.py)
  - Requirements Corpus (scripts/gen_requirements_corpus.py)
  - TestGen Corpus (scripts/gen_testgen_corpus.py)
  - Answer Quality Corpus (scripts/gen_answer_quality_corpus.py)

Usage:
  python skills/corpus-guardian/scripts/corpus_guard.py --check
  python skills/corpus-guardian/scripts/corpus_guard.py --generate
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CORPUS_SCRIPTS = (
    "scripts/gen_rca_corpus.py",
    "scripts/gen_requirements_corpus.py",
    "scripts/gen_testgen_corpus.py",
    "scripts/gen_answer_quality_corpus.py",
)


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(10):
        if (cur / "pyproject.toml").is_file() and (cur / "architecture.yaml").is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    raise RuntimeError(f"Could not locate repo root from {start}")


def run_corpus_guard(repo_root: Path, check_only: bool) -> int:
    action_flag = "--check" if check_only else "--write"
    failed: list[str] = []

    for rel_script in CORPUS_SCRIPTS:
        script_path = repo_root / rel_script
        if not script_path.is_file():
            logger.error("Corpus generator script missing: %s", script_path)
            failed.append(rel_script)
            continue

        cmd = [sys.executable, str(script_path), action_flag]
        logger.info("Executing %s %s...", rel_script, action_flag)
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error(
                "Corpus check failed for %s (exit %d):\n%s\n%s",
                rel_script,
                proc.returncode,
                proc.stdout,
                proc.stderr,
            )
            failed.append(rel_script)
        else:
            logger.info("Passed: %s", rel_script)

    if failed:
        logger.error("Corpora failing %s: %s", action_flag, ", ".join(failed))
        return 1

    logger.info("All %d synthetic corpora verified clean.", len(CORPUS_SCRIPTS))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", default=True, help="Check corpora freshness without writing")
    mode.add_argument("--generate", action="store_true", help="Regenerate all corpora in-place")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    repo_root = _find_repo_root(Path(__file__))
    check_only = not args.generate

    return run_corpus_guard(repo_root, check_only=check_only)


if __name__ == "__main__":
    sys.exit(main())
