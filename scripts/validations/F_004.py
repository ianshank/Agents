#!/usr/bin/env python3
"""Validation script for Feature F-004: First Real Skill (openai-judge)."""

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


def validate_f004() -> bool:
    project_root = Path(__file__).resolve().parent.parent.parent
    val_script = project_root / "scripts" / "validate_skill.py"
    skill_dir = project_root / "skills" / "openai-judge"

    if not val_script.is_file():
        logger.error("FAIL: validate_skill.py not found at %s", val_script)
        return False
    if not skill_dir.is_dir():
        logger.error("FAIL: openai-judge skill dir not found at %s", skill_dir)
        return False

    cmd = [sys.executable, str(val_script), "--skill", str(skill_dir), "--tier", "structural,behavioral"]
    return run_subprocess_check(cmd, cwd=project_root, timeout=120, label="F-004 validation")


def main() -> int:
    configure_logging()
    return 0 if validate_f004() else 1


if __name__ == "__main__":
    sys.exit(main())
