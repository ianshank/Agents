#!/usr/bin/env python3
"""Validation script for F-001 – Harness initialized.

Checks:
    1. ``HARNESS_SPEC.md`` exists.
    2. ``features.yaml`` exists and parses as valid YAML with a ``features`` key.
    3. ``features.schema.json`` exists and parses as valid JSON.
    4. ``scripts/validate.py`` exists.
    5. ``scripts/select_next.py`` exists.

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import List

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Resolve the project root (two levels up from this script)."""
    return Path(__file__).resolve().parent.parent.parent


def _check_file_exists(root: Path, rel_path: str, errors: List[str]) -> bool:
    """Assert that *rel_path* exists under *root*. Append to *errors* on failure."""
    full = root / rel_path
    if not full.exists():
        msg = f"Missing: {rel_path}"
        errors.append(msg)
        logger.error(msg)
        return False
    logger.info("OK: %s exists", rel_path)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all F-001 validation checks."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    root = _project_root()
    errors: List[str] = []

    # 1. HARNESS_SPEC.md
    _check_file_exists(root, "HARNESS_SPEC.md", errors)

    # 2. features.yaml – exists + parseable with 'features' key
    features_path = root / "features.yaml"
    if not features_path.exists():
        errors.append("Missing: features.yaml")
        logger.error("Missing: features.yaml")
    else:
        try:
            with features_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict) or "features" not in data:
                msg = "features.yaml does not contain a top-level 'features' key"
                errors.append(msg)
                logger.error(msg)
            else:
                logger.info("OK: features.yaml parses with 'features' key")
        except yaml.YAMLError as exc:
            msg = f"features.yaml parse error: {exc}"
            errors.append(msg)
            logger.error(msg)

    # 3. features.schema.json – exists + valid JSON
    schema_path = root / "features.schema.json"
    if not schema_path.exists():
        errors.append("Missing: features.schema.json")
        logger.error("Missing: features.schema.json")
    else:
        try:
            with schema_path.open("r", encoding="utf-8") as fh:
                json.load(fh)
            logger.info("OK: features.schema.json parses as valid JSON")
        except json.JSONDecodeError as exc:
            msg = f"features.schema.json parse error: {exc}"
            errors.append(msg)
            logger.error(msg)

    # 4. scripts/validate.py
    _check_file_exists(root, "scripts/validate.py", errors)

    # 5. scripts/select_next.py
    _check_file_exists(root, "scripts/select_next.py", errors)

    # Summary
    if errors:
        logger.error("F-001 FAILED with %d error(s):", len(errors))
        for err in errors:
            logger.error("  • %s", err)
        return 1

    logger.info("F-001 passed ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
