#!/usr/bin/env python3
"""Validation script for Feature F-003: Skill Template and Validator Infrastructure."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import configure_logging

logger = logging.getLogger(__name__)


def validate_f003() -> bool:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 1. Check docs/SKILL_TEMPLATE.md exists
    skill_temp = os.path.join(project_root, "docs", "SKILL_TEMPLATE.md")
    if not os.path.isfile(skill_temp):
        logger.error("FAIL: Missing SKILL_TEMPLATE.md at %s", skill_temp)
        return False

    # 2. Check docs/SKILL_VALIDATION_TEMPLATE.md exists
    val_temp = os.path.join(project_root, "docs", "SKILL_VALIDATION_TEMPLATE.md")
    if not os.path.isfile(val_temp):
        logger.error("FAIL: Missing SKILL_VALIDATION_TEMPLATE.md at %s", val_temp)
        return False

    # 3. Check scripts/validate_skill.py exists
    val_script = os.path.join(project_root, "scripts", "validate_skill.py")
    if not os.path.isfile(val_script):
        logger.error("FAIL: Missing validate_skill.py at %s", val_script)
        return False

    # 4. Check scripts/validate_skill.py is importable (no syntax errors)
    try:
        spec = importlib.util.spec_from_file_location("validate_skill", val_script)
        if spec is None or spec.loader is None:
            logger.error("FAIL: Could not create import spec for validate_skill.py")
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error("FAIL: validate_skill.py has syntax or import errors: %s", e)
        return False

    # 5. Check skills/ directory exists
    skills_dir = os.path.join(project_root, "skills")
    os.makedirs(skills_dir, exist_ok=True)
    if not os.path.isdir(skills_dir):
        logger.error("FAIL: skills/ is not a directory at %s", skills_dir)
        return False

    logger.info("OK: F-003 validation passed.")
    return True


def main() -> int:
    configure_logging()
    return 0 if validate_f003() else 1


if __name__ == "__main__":
    sys.exit(main())
