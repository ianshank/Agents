#!/usr/bin/env python3
"""Validation script for F-050 — skills CI coverage floor (ADR 0030).

Asserts three related invariants stay in place:
    1. ``skills-ci.yml`` triggers on any ``skills/**`` change, not a per-skill allowlist --
       ``dataset-lint`` was previously omitted from a 7-entry ``paths:`` list and its
       dedicated job silently never ran on its own changes.
    2. The ``all-skills`` job runs a structural floor over every ``skills/*/`` directory
       plus the marketplace registry validation and the vendored-script drift guard --
       repo-level guards that, before this job, only ran when a PR happened to also touch
       ``scripts/**`` (via ``quality-gates.yml``).
    3. The ``all-skills`` job's registration + job-coverage guard enumerates the three
       ADR 0030 "subjective skill" exemptions and self-checks each against
       ``evals/evals.json`` so a stale exemption fails loudly instead of drifting silently
       (the exact failure class this feature exists to close, recreated one level up).
    4. This script's own coverage wiring exists: it is exercised by
       ``tests/test_validation_scripts.py`` and measured by ``quality-gates.yml``'s
       coverage step -- without both, F-050 would only be smoke-tested by
       ``scripts/validate.py --tier fast`` and never part of the offline pytest suite that
       ``eval-harness-ci.yml`` runs on ``.github/``-only edits (the suite that exists because
       F-031/F-037 broke silently on a ``.github/``-only PR that ``quality-gates.yml``'s path
       filter missed -- PR #64).

Deterministic and offline: reads workflow/config/source files only, runs nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
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

logger = logging.getLogger(__name__)

_SKILLS_CI = os.path.join(".github", "workflows", "skills-ci.yml")
_QUALITY_GATES_CI = os.path.join(".github", "workflows", "quality-gates.yml")
_TEST_VALIDATION_SCRIPTS = os.path.join("tests", "test_validation_scripts.py")

_EXEMPT_SKILLS = (
    "hierarchical-recursive-brainstorm",
    "openspec-quality-plan",
    "openspec-peer-review",
)


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    skills_ci = _read(_SKILLS_CI)

    # 1. Trigger is a single glob covering every skill, not a per-skill allowlist. Both
    # push and pull_request carry the entry, so the literal appears at least twice.
    _check(
        skills_ci.count('"skills/**"') >= 2,
        "skills-ci.yml triggers on skills/** (push and pull_request), not a per-skill allowlist",
        errors,
    )

    # 2. The all-skills job exists and runs the structural floor + marketplace + drift guard.
    # These commands are never routed through the ADR 0021 delegation chain (the job is a
    # repo-level guard over the skill *set*, explicitly out of that scope -- ADR 0030), so
    # they are asserted directly rather than through _common.ci_enforces, which exists for
    # steps that face real delegation ambiguity (see check 5 below for a contrast).
    _check("all-skills:" in skills_ci, "skills-ci.yml defines the all-skills job", errors)
    _check(
        'validate_skill.py --skill "$d" --tier structural' in skills_ci,
        "all-skills job runs the structural tier over every discovered skill directory",
        errors,
    )
    _check(
        "python scripts/skill_marketplace.py validate" in skills_ci,
        "all-skills job validates the marketplace registry",
        errors,
    )
    _check(
        "python scripts/check_skill_script_drift.py" in skills_ci,
        "all-skills job runs the vendored-script drift guard",
        errors,
    )

    # 3. The registration + job-coverage guard enumerates the ADR 0030 exemptions and
    # self-checks each against evals/evals.json so a stale exemption fails loudly.
    _check("EXEMPT" in skills_ci, "all-skills job defines an EXEMPT mapping", errors)
    for name in _EXEMPT_SKILLS:
        _check(
            f'"{name}"' in skills_ci,
            f"EXEMPT covers {name}",
            errors,
        )
    _check(
        "evals.json" in skills_ci and "stale" in skills_ci,
        "EXEMPT entries are re-checked against evals/evals.json (a stale exemption fails, not drifts silently)",
        errors,
    )

    # 4. This validator's own coverage wiring: exercised by the offline pytest suite and
    # measured by quality-gates.yml's coverage step, not just smoke-tested by validate.py.
    test_validation_scripts = _read(_TEST_VALIDATION_SCRIPTS)
    _check(
        "F_050" in test_validation_scripts,
        "F_050 is imported and exercised by tests/test_validation_scripts.py",
        errors,
    )
    quality_gates_ci = _read(_QUALITY_GATES_CI)
    _check(
        "--cov=F_050" in quality_gates_ci,
        "quality-gates.yml measures coverage of F_050",
        errors,
    )

    return report(logger, "F-050", errors)


if __name__ == "__main__":
    raise SystemExit(main())
