#!/usr/bin/env python3
"""Validation script for F-028 — openai-judge skill modernization.

Deterministic and offline. Asserts the openai-judge skill now meets the newer
skill convention (a ``tests/`` dir, a ``ruff.toml``, and a ``validator_version``
frontmatter key), that it still passes structural validation, and that the
marketplace registry entry matches the bumped SKILL.md version.

    1. SKILL.md frontmatter carries ``validator_version: '2.0'``.
    2. ``skills/openai-judge/tests/`` and ``ruff.toml`` exist.
    3. The skill passes structural validation (reusing validate_skill.py read-only).
    4. The marketplace registry version matches the SKILL.md version (semver).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from _common import check as _check
from _common import configure_logging, report

import yaml

from validate_skill import check_structural, parse_frontmatter  # canonical validator, read-only

_SKILL = os.path.join(_ROOT, "skills", "openai-judge")


def validate_f028() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-028")
    errors: list[str] = []

    fm, _ = parse_frontmatter(os.path.join(_SKILL, "SKILL.md"))
    _check(fm is not None, "SKILL.md has parseable frontmatter", errors)
    fm = fm or {}
    _check(str(fm.get("validator_version")) == "2.0", "frontmatter validator_version is 2.0", errors)

    _check(os.path.isdir(os.path.join(_SKILL, "tests")), "tests/ directory exists", errors)
    _check(os.path.isfile(os.path.join(_SKILL, "ruff.toml")), "ruff.toml exists", errors)

    struct_errs, _ = check_structural(_SKILL, os.path.join(_SKILL, "evals", "evals.json"))
    _check(not struct_errs, f"skill passes structural validation ({struct_errs})", errors)

    with open(os.path.join(_ROOT, "skills", "marketplace.yaml"), encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    entry = next((s for s in registry["skills"] if s["name"] == "openai-judge"), None)
    _check(entry is not None, "openai-judge listed in marketplace.yaml", errors)
    if entry is not None:
        _check(
            str(entry["version"]) == str(fm.get("version")),
            f"marketplace version {entry['version']!r} matches SKILL.md {fm.get('version')!r}",
            errors,
        )

    return report(logger, "F-028", errors)


if __name__ == "__main__":
    sys.exit(validate_f028())
