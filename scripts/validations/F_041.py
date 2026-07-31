#!/usr/bin/env python3
"""Validation script for F-041 — claude-foundation/tests/ protected-path gap.

An independent deep audit of the merged F-039 work (protected-path coverage for the
eval_harness ecosystem's sibling packages) found that ``claude-foundation/`` -- structurally
identical to the four packages F-039 protects (its own ``pyproject.toml``, ``Makefile``,
isolated CI workflow, and ``tests/`` directory) -- was missed by that sweep. Its
``tests/test_eval_gate.py`` directly exercises an eval-integrity-relevant gate
(``foundation_tools.eval_gate``), so leaving it unprotected let a contributor weaken that
gate's pass/fail logic in an unrelated PR with no ``eval-change-approved`` label or
``.github/CODEOWNERS`` review required.

This validator locks in the fix: ``claude-foundation/tests/**`` must be a protected path,
and ``.github/CODEOWNERS`` must mirror it. Deliberately narrower in scope than F-039: this
does not require ``claude-foundation`` to also carry a duplicated ``__all__`` public-surface
guard (F-039's ``_PACKAGES``-driven checks) -- that guard exists to protect the
config-selectable/importable Python surface the four ``eval_harness`` sibling packages
expose to each other and to consumers, which is a different concern than
``claude-foundation``'s (a standalone Claude Code plugin, not part of that import graph).
This validator closes only the protected-path gap the audit actually confirmed.

Deterministic and offline: reads config/source files and the in-process pattern list; runs
nothing.

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


def main() -> int:
    configure_logging()
    errors: list[str] = []

    _check(
        os.path.isdir(os.path.join(_ROOT, "claude-foundation", "tests")),
        "claude-foundation/tests/ exists (this validator is a no-op if it's ever extracted/removed)",
        errors,
    )

    import eval_protected_paths as epp

    _check(
        "claude-foundation/tests/**" in epp.PROTECTED_PATTERNS,
        "eval_protected_paths.PROTECTED_PATTERNS includes 'claude-foundation/tests/**'",
        errors,
    )
    _check(
        epp.is_protected("claude-foundation/tests/test_eval_gate.py"),
        "claude-foundation/tests/test_eval_gate.py resolves as protected (is_protected() == True)",
        errors,
    )
    _check(
        epp.is_protected("claude-foundation/tests/anything.py"),
        "claude-foundation/tests/ is_protected() (a representative path resolves True)",
        errors,
    )

    with open(os.path.join(_ROOT, ".github", "CODEOWNERS"), encoding="utf-8") as fh:
        codeowners = fh.read()
    _check(
        "/claude-foundation/tests/" in codeowners,
        ".github/CODEOWNERS covers /claude-foundation/tests/",
        errors,
    )

    return report(logger, "F-041", errors)


if __name__ == "__main__":
    raise SystemExit(main())
