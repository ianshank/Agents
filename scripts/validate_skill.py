#!/usr/bin/env python3
"""Validate a skill end to end.

  python scripts/validate_skill.py --skill . --tier structural
  python scripts/validate_skill.py --skill . --tier structural,behavioral

structural = no side effects; behavioral = runs the task and checks real outputs.
Behavioral writes only under <skill>/.skill-validation/. Exit 0 iff every selected check passes.

This module is a thin wrapper around the shared skill validator in skills/common/skill_validator.py.
"""

from __future__ import annotations

import argparse
import os
import sys

# Find skills/common directory by traversing up from this file's location.
# This code works identically from both scripts/validate_skill.py and skills/*/scripts/validate_skill.py.
_CURRENT = os.path.dirname(os.path.abspath(__file__))
_VALIDATOR_PATH = None
while _CURRENT != os.path.dirname(_CURRENT):
    _CANDIDATE = os.path.join(_CURRENT, "skills", "common")
    if os.path.isdir(_CANDIDATE) and os.path.isfile(os.path.join(_CANDIDATE, "skill_validator.py")):
        _VALIDATOR_PATH = _CANDIDATE
        break
    _CURRENT = os.path.dirname(_CURRENT)

if _VALIDATOR_PATH and _VALIDATOR_PATH not in sys.path:
    sys.path.insert(0, _VALIDATOR_PATH)

from skill_validator import check_behavioral, check_structural  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default=".")
    ap.add_argument("--evals", default="evals/evals.json")
    ap.add_argument("--tier", default="structural")
    ap.add_argument("--timeout", type=int, default=120, help="per-command timeout in seconds")
    args = ap.parse_args()
    tiers = {t.strip() for t in args.tier.split(",") if t.strip()}
    errs: list[str] = []
    warns: list[str] = []
    if "structural" in tiers:
        e, w = check_structural(args.skill, args.evals)
        errs += e
        warns += w
    if "behavioral" in tiers:
        errs += check_behavioral(args.skill, args.evals, args.timeout)
    for warning in warns:
        print(f"[warn] {warning}")
    if errs:
        print("SKILL VALIDATION FAILED:\n  - " + "\n  - ".join(errs))
        return 1
    print(f"OK: skill passed tier(s) {sorted(tiers)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
