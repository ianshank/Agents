"""Shared helpers for the per-feature validation scripts (F_0XX).

Single-sources the logging convention and the pass/fail check that every
validator used to duplicate verbatim. Importable both standalone
(``python scripts/validations/F_0XX.py`` puts this directory on ``sys.path``)
and under pytest, after ensuring the repo ``scripts/`` directory is importable
so the canonical ``_cli.configure_logging`` can be reused.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from _cli import configure_logging

__all__ = ["check", "ci_enforces", "configure_logging", "delegates_to_gate", "report"]

_logger = logging.getLogger("validations")

# Any link in the ADR 0021 delegation chain: the composite action, the Makefile target it
# runs, or the generated gate script that target invokes. Matching any of them keeps the
# validators from pinning one spelling of the wiring.
_DELEGATION_TOKENS = ("run-quality-gate", "quality-gate.sh", "make check")


def check(condition: bool, msg: str, errors: list[str]) -> bool:
    """Record a single validation check: append + log on failure, log on success."""
    if not condition:
        errors.append(msg)
        _logger.error("FAIL: %s", msg)
        return False
    _logger.info("OK: %s", msg)
    return True


def delegates_to_gate(workflow: str) -> bool:
    """True if a workflow runs the shared quality gate instead of inline steps.

    ADR 0021 rewires the per-package workflows to the ``run-quality-gate`` composite
    action, which runs ``make check`` -> ``./scripts/quality-gate.sh all``.
    """
    return any(token in workflow for token in _DELEGATION_TOKENS)


def ci_enforces(workflow: str, gate: str, *, inline: str, in_gate: str) -> bool:
    """True if CI runs a step, whether wired inline or delegated to the shared gate.

    Assert the *guarantee* (the step runs in CI), not one wiring of it. Before ADR 0021
    these steps lived inline in the workflow; after it they live in the generated
    ``scripts/quality-gate.sh`` the workflow delegates to. Validators that pinned the
    inline spelling failed the moment the delegation landed (PR #64) even though the
    underlying guarantee was fully intact -- and, because the protected-path guard did
    not run on that PR, the failure went undetected on ``main``.

    Both arguments are file *contents*, not paths, so this stays pure and unit-testable.
    """
    if inline in workflow:
        return True
    return delegates_to_gate(workflow) and in_gate in gate


def report(logger: logging.Logger, label: str, errors: list[str]) -> int:
    """Emit the standard pass/fail summary and return the process exit code."""
    if errors:
        logger.error("%s FAILED with %d error(s):", label, len(errors))
        for err in errors:
            logger.error("  - %s", err)
        return 1
    logger.info("%s passed", label)
    return 0
