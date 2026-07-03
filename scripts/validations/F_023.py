#!/usr/bin/env python3
"""Validation script for F-023 - Skill Marketplace.

Checks:
    1. ``skills/marketplace.yaml`` parses and validates against the schema.
    2. Every registered skill exists, has a semver ``version`` in SKILL.md
       matching the registry, and passes structural validation.
    3. At least the three first-party skills are registered.
    4. ``validate_skill.check_structural`` default behaviour is unchanged for a
       versionless skill (the marketplace enforces ``version``, not validate_skill).

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile

# Ensure scripts/ and this directory are importable when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    import skill_marketplace as mkt
    import validate_skill

    root = os.path.dirname(_SCRIPTS)
    registry_path = os.path.join(root, "skills", "marketplace.yaml")
    schema_path = os.path.join(root, "skills", "marketplace.schema.json")

    # 1-2. full validation is clean
    val_errors = mkt.validate_registry(registry_path, schema_path)
    _check(val_errors == [], f"marketplace registry validates ({len(val_errors)} errors)", errors)
    for e in val_errors:
        logger.error("  registry error: %s", e)

    # 3. first-party skills registered
    registry = mkt.load_registry(registry_path)
    names = {s.get("name") for s in registry.get("skills", [])}
    for expected in ("openai-judge", "architecture-drift-guard", "eval-corpus-forge"):
        _check(expected in names, f"skill '{expected}' registered", errors)

    # 4. validate_skill default behaviour unchanged for a versionless skill
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "evals"), exist_ok=True)
        with open(os.path.join(td, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                "---\nname: tmp\ndescription: a temp skill for the compat check\ncompatibility: python>=3.10\n---\n\n# tmp\n"
            )
        struct_errs, _ = validate_skill.check_structural(td, "evals/evals.json")
        # A versionless skill must NOT fail structural validation (no 'version' requirement there).
        version_required = any("version" in e.lower() for e in struct_errs)
        _check(not version_required, "validate_skill does not require 'version' (default mode unchanged)", errors)

    return report(logger, "F-023", errors)


if __name__ == "__main__":
    sys.exit(main())
