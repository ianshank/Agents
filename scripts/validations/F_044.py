#!/usr/bin/env python3
"""Validation script for F-044 — one-off agent-domain backfill migration.

Deterministic and offline: reads the migration + its committed SHA list only, runs
nothing (no git, no store writes). The migration's pure logic is covered by
tests/test_agent_domain_backfill.py; this gate pins its SAFETY properties.

    1. The migration and its hand-verified SHA list are committed.
    2. It is dry-run by default (--apply required to write) and backs up before writing.
    3. It refuses to rewrite HUMAN_AUDIT records.
    4. It does NOT auto-push the data branch (the remote rewrite is a manual,
       snapshot-guarded step — the file explicitly warns against store_sync push).

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
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
_MIGRATION = os.path.join("scripts", "migrations", "agent_domain_backfill.py")
_SHAS = os.path.join("scripts", "migrations", "agent-backfill-2026-07-22.txt")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def validate_f044() -> int:
    configure_logging()
    errors: list[str] = []

    shas = _read(_SHAS)
    sha_lines = [ln for ln in shas.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    _check(len(sha_lines) > 0, "committed hand-verified agent-SHA list is non-empty", errors)
    _check(
        all(len(ln.split()) >= 2 for ln in sha_lines),
        "every SHA line carries an explicit agent_version",
        errors,
    )

    mig = _read(_MIGRATION)
    for needle, why in [
        ('"--apply"', "write is opt-in via --apply"),
        ('action="store_true"', "--apply is a flag (dry-run is the default)"),
        ("dry-run", "dry-run is the documented default"),
        ("pre-backfill.bak", "backs up the store before overwriting (reversible)"),
        ("HUMAN_AUDIT", "guards the authoritative label"),
        ("refusing", "refuses to rewrite a HUMAN_AUDIT record"),
        ("NOT store_sync push", "does not auto-push; remote rewrite is a manual snapshot-guarded step"),
    ]:
        _check(needle in mig, f"migration: {why}", errors)

    return report(logger, "F-044", errors)


def main() -> int:
    return validate_f044()


if __name__ == "__main__":
    sys.exit(main())
