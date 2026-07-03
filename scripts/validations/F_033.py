#!/usr/bin/env python3
"""Validation script for F-033 — scheduled outcome labeller.

Deterministic and offline: reads the workflow file only, runs nothing.

    1. ``outcome-labeller.yml`` runs on a schedule and via workflow_dispatch.
    2. ``checks: read`` is granted — without it the Checks API 403s and the
       detector silently degrades every matured record to an optimistic
       ``timeout_clean``; ``fetch-depth: 0`` for revert-footer visibility.
    3. Ordering (by string index): precondition guard (shallow-repository
       probe + live check-runs probe) -> store pull -> labeller -> store push.
       Push is the final store touch, so any earlier failure leaves the
       remote store untouched.
    4. The labeller path structurally cannot write the authoritative label:
       no ``audit_sampler`` / ``HUMAN_AUDIT`` reference anywhere in the file.

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
_WORKFLOW = os.path.join(".github", "workflows", "outcome-labeller.yml")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def validate_f033() -> int:
    configure_logging()
    errors: list[str] = []
    wf = _read(_WORKFLOW)

    _check("schedule:" in wf and "cron:" in wf, "labeller runs on a schedule", errors)
    _check("workflow_dispatch:" in wf, "labeller is manually dispatchable", errors)
    _check("fetch-depth: 0" in wf, "full history for revert-footer detection", errors)
    _check("checks: read" in wf, "Checks API scope granted (anti-optimism guard)", errors)
    _check("GH_TOKEN" in wf, "gh authentication wired", errors)

    order = [
        ("--is-shallow-repository", "shallow-clone guard"),
        ("rev-parse HEAD)/check-runs", "live Checks API probe"),
        ("store_sync pull", "store pull"),
        ("agent_core.outcome_labeller", "labeller invocation"),
        ("store_sync push", "store push (final store touch)"),
    ]
    positions = [(wf.find(needle), needle, why) for needle, why in order]
    for pos, needle, why in positions:
        _check(pos != -1, f"{why} present ({needle})", errors)
    if all(pos != -1 for pos, _, _ in positions):
        _check(
            [pos for pos, _, _ in positions] == sorted(pos for pos, _, _ in positions),
            "guard -> pull -> label -> push ordering holds",
            errors,
        )

    _check(
        "audit_sampler" not in wf and "HUMAN_AUDIT" not in wf,
        "labeller cannot reach the authoritative (human-audit) label path",
        errors,
    )

    return report(logger, "F-033", errors)


def main() -> int:
    return validate_f033()


if __name__ == "__main__":
    sys.exit(main())
