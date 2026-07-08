#!/usr/bin/env python3
"""Validation script for F-039 — claude-foundation extraction + M7 dogfood.

Deterministic and offline: reads the working tree only, runs nothing.

    1. The claude-foundation/ staging directory is GONE (extracted to its own repo)
       and so is its root orchestration workflow — they vanish together (F-037).
    2. The agents repo consumes the plugin by config: .claude/settings.json registers
       the claude-foundation marketplace pinned to a tag (source ref) and enables the
       foundation plugin.
    3. The four domain skills survive as real tracked directories (not symlinks, with
       SKILL.md) — extraction must not delete or vendor them.
    4. No generic foundation skill (plan / code-review / test-first / c4-docs) was
       duplicated into skills/ (routing rule, ADR 0017).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_STAGING = "claude-foundation"
_STAGING_WORKFLOW = os.path.join(".github", "workflows", "claude-foundation-ci.yml")
_SETTINGS = os.path.join(".claude", "settings.json")
_DOMAIN_SKILLS = ("openai-judge", "architecture-drift-guard", "eval-corpus-forge", "model-bench")
_GENERIC_SKILLS = ("plan", "code-review", "test-first", "c4-docs")


def _abs(rel: str) -> str:
    return os.path.join(_ROOT, rel)


def _check_dogfood_config(errors: list[str]) -> None:
    settings_path = _abs(_SETTINGS)
    if not _check(os.path.exists(settings_path), ".claude/settings.json exists (M7 dogfood config)", errors):
        return
    with open(settings_path, encoding="utf-8") as fh:
        settings = json.load(fh)
    src = settings.get("extraKnownMarketplaces", {}).get("claude-foundation", {}).get("source", {})
    _check(
        src.get("repo") == "ianshank/claude-foundation",
        "settings registers the claude-foundation marketplace at the extracted repo",
        errors,
    )
    ref = src.get("ref")
    # Pin must be a semver release tag (rejects empty/garbage refs) — matched by pattern
    # rather than a hardcoded version so deliberate pin bumps don't require editing the gate.
    _check(
        bool(ref and re.fullmatch(r"v\d+\.\d+\.\d+", ref)),
        "marketplace pins a semver release tag via the source ref (e.g. v1.0.0)",
        errors,
    )
    _check(
        settings.get("enabledPlugins", {}).get("foundation@claude-foundation") is True,
        "the foundation plugin is enabled (explicit true)",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. Staging dir + its root workflow are gone together.
    _check(not os.path.isdir(_abs(_STAGING)), "claude-foundation staging dir removed", errors)
    _check(
        not os.path.exists(_abs(_STAGING_WORKFLOW)),
        "claude-foundation root workflow removed",
        errors,
    )

    # 2. Pinned-plugin consumption config present.
    _check_dogfood_config(errors)

    # 3. The four domain skills survive (real dirs, not symlinks, SKILL.md present).
    for skill in _DOMAIN_SKILLS:
        skill_dir = _abs(os.path.join("skills", skill))
        _check(
            os.path.isdir(skill_dir) and not os.path.islink(skill_dir),
            f"domain skill {skill} is a real tracked directory",
            errors,
        )
        _check(
            os.path.exists(os.path.join(skill_dir, "SKILL.md")),
            f"domain skill {skill} keeps its SKILL.md",
            errors,
        )

    # 4. No generic foundation skill duplicated into skills/.
    for generic in _GENERIC_SKILLS:
        _check(
            not os.path.isdir(_abs(os.path.join("skills", generic))),
            f"generic skill '{generic}' is not duplicated into skills/ (ADR 0017 routing rule)",
            errors,
        )

    return report(logger, "F-039", errors)


if __name__ == "__main__":
    raise SystemExit(main())
