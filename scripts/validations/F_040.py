#!/usr/bin/env python3
"""Validation script for F-040 — merge-gate soak-stats (store_sync.soak_progress).

Deterministic and offline: reads source files only, runs nothing.

    1. store_sync exposes a pure ``soak_progress(records, target)`` summary and
       re-exports it on the package public surface.
    2. The per-domain cold-start floor is the audit-config field
       (``AuditConfig.per_domain_floor``), not a hardcoded literal.
    3. The ``stats`` CLI gains an opt-in ``--soak-target`` that adds a reserved
       ``_soak`` block; the bare-stats output stays unchanged (default-off).
    4. Tests exist: the soak summary, the no-mutation property (I-2 TCB
       carve-out), and the byte-identical default CLI output.

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
_PKG = os.path.join("agent-core", "agent_core", "store_sync")
_TESTS = os.path.join("agent-core", "tests", "test_store_sync.py")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _read_pkg() -> str:
    """Union of the store_sync package sources (soak_progress lives in a submodule).

    Only regular ``*.py`` files are read, so a partial checkout fails the needle
    checks cleanly via ``_check`` rather than crashing ``_read``.
    """
    pkg_dir = os.path.join(_ROOT, _PKG)
    if not os.path.isdir(pkg_dir):
        return ""
    parts = [
        _read(os.path.join(_PKG, name))
        for name in sorted(os.listdir(pkg_dir))
        if name.endswith(".py") and os.path.isfile(os.path.join(pkg_dir, name))
    ]
    return "\n".join(parts)


def validate_f040() -> int:
    configure_logging()
    errors: list[str] = []

    pkg = _read_pkg()
    init = _read(os.path.join(_PKG, "__init__.py"))
    tests = _read(_TESTS)

    for needle, why in [
        ("def soak_progress(", "pure soak_progress summary exists"),
        ("AuditConfig.per_domain_floor", "cold-start floor is the audit-config field, not a literal"),
        ("velocity_per_day", "soak report includes a merge-velocity signal"),
        ("days_to_target", "soak report includes an ETA-to-target signal"),
    ]:
        _check(needle in pkg, f"store_sync: {why}", errors)

    _check('"soak_progress"' in init, "soak_progress is on the package public surface (__all__)", errors)
    _check("--soak-target" in init, "stats CLI exposes the opt-in --soak-target flag", errors)
    _check('"_soak"' in init, "soak block uses the reserved _soak key (no domain collision)", errors)
    _check(
        "soak_target is not None" in init,
        "the _soak block is default-off (bare stats output unchanged)",
        errors,
    )

    for needle, why in [
        ("def test_soak_progress", "soak summary is unit-tested"),
        ("never_mutates", "no-mutation property is tested (I-2 TCB carve-out)"),
        ("default_unchanged", "byte-identical default CLI output is tested"),
    ]:
        _check(needle in tests, f"tests: {why}", errors)

    return report(logger, "F-040", errors)


def main() -> int:
    return validate_f040()


if __name__ == "__main__":
    sys.exit(main())
