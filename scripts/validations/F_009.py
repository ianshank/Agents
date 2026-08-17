#!/usr/bin/env python3
"""Validation script for Feature F-009: architecture drift-guard skill + dogfood gate.

Checks three things, all deterministic:
  1. The skill passes its own structural+behavioral self-check.
  2. The dogfood drift gate passes against the repo manifest (exit 0).
  3. The dogfood freshness gate passes (committed architecture.mmd is current).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import configure_logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "architecture-drift-guard")
DRIFT_CHECK = os.path.join(SKILL_DIR, "scripts", "drift_check.py")
MERMAID_GEN = os.path.join(SKILL_DIR, "scripts", "mermaid_gen.py")
MANIFEST = os.path.join(PROJECT_ROOT, "architecture.yaml")
DIAGRAM = os.path.join(PROJECT_ROOT, "architecture.mmd")


def _run(cmd: list[str], *, cwd: str) -> bool:
    logger.info("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("FAIL: command crashed: %s", exc)
        return False
    if res.stdout:
        logger.info(res.stdout)
    if res.returncode != 0:
        if res.stderr:
            logger.error(res.stderr)
        logger.error("FAIL: exited %d", res.returncode)
        return False
    return True


def validate_f009() -> bool:
    val_script = os.path.join(SKILL_DIR, "scripts", "validate_skill.py")
    for path in (val_script, DRIFT_CHECK, MERMAID_GEN, MANIFEST, DIAGRAM):
        if not os.path.exists(path):
            logger.error("FAIL: required path missing: %s", path)
            return False

    # 1. Skill self-check (run from the skill dir, like F_004).
    if not _run(
        [sys.executable, val_script, "--skill", SKILL_DIR, "--tier", "structural,behavioral"],
        cwd=SKILL_DIR,
    ):
        return False

    # 2. Dogfood drift gate (run from repo root so sys_path ./src, ./agent-core resolve).
    if not _run([sys.executable, DRIFT_CHECK, "--manifest", MANIFEST], cwd=PROJECT_ROOT):
        return False

    # 3. Dogfood freshness gate.
    if not _run(
        [sys.executable, MERMAID_GEN, "--manifest", MANIFEST, "--check", "-o", DIAGRAM],
        cwd=PROJECT_ROOT,
    ):
        return False

    logger.info("OK: F-009 validation passed.")
    return True


def main() -> int:
    configure_logging()
    return 0 if validate_f009() else 1


if __name__ == "__main__":
    sys.exit(main())
