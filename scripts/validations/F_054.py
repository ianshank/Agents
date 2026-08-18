#!/usr/bin/env python3
"""Validation script for F-054 - Quality-gate coverage-threshold hardening stays enforced.

Asserts the `harden-quality-gate-integrity` fix (see
docs/plans/orbital-drift-alignment/PLAN.md Phase 1) stays in place across every generated
``quality-gate.sh`` and every package whose coverage-exclude regex it corrected:

    1. Each of the 7 packages' generated ``scripts/quality-gate.sh`` prints an
       ignored-override notice for ``COVERAGE_SOURCE``, ``COV_FAIL_UNDER`` and
       ``PYTEST_ADDOPTS`` -- so a live env override is visible, never silently honored.
    2. None of the 7 interpolates a raw ``"$COV_FAIL_UNDER"`` into ``--cov-fail-under=`` or a
       raw single-source ``"$COVERAGE_SOURCE"`` into ``--cov=`` -- both must be
       generation-time literals, not a live env reference an operator could override.
    3. ``unset PYTEST_ADDOPTS`` appears ahead of every direct ``pytest`` invocation: twice in
       the 6 packages with only ``do_test``/``do_coverage``, a third time in root's
       hand-maintained ``do_extra()`` (below the marker, where the generator cannot reach).
    4. The 4 packages whose ``exclude_also`` regex was unanchored (`agent-core`,
       `behavioral-regression`, `flow-protocol`, `flow-corpus`) now carry the anchored
       ``"^\\s*\\.\\.\\.$"`` pattern, matching root ``pyproject.toml``/``scripts/.coveragerc``.

Deterministic and offline: reads committed files only, runs nothing, executes no pytest.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure scripts/ and this directory are importable when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)

# The 7 real, regenerated quality-gate.sh copies (ADR-independent list: this IS the
# authoritative enumeration, mirroring how PLAN.md Phase 1 names them). Deliberately excludes
# skills/project-setup/evals/fixtures/with-gate/scripts/quality-gate.sh -- a frozen test
# fixture, never regenerated, and asserting hardened text against it would be a false demand.
_GATE_SCRIPTS: tuple[str, ...] = (
    "scripts/quality-gate.sh",
    "agent-core/scripts/quality-gate.sh",
    "behavioral-regression/scripts/quality-gate.sh",
    "claude-foundation/scripts/quality-gate.sh",
    os.path.join("experiments", "backend-validation", "scripts", "quality-gate.sh"),
    "flow-corpus/scripts/quality-gate.sh",
    "flow-protocol/scripts/quality-gate.sh",
)

# The 4 packages whose exclude_also regex was unanchored (root pyproject.toml and
# scripts/.coveragerc were already correct before this change and carry no exclude_also key --
# root uses exclude_lines -- so they are not re-asserted here; F-031 already covers
# scripts/.coveragerc's floor and shape).
_ANCHORED_REGEX_PYPROJECTS: tuple[str, ...] = (
    "agent-core/pyproject.toml",
    "behavioral-regression/pyproject.toml",
    "flow-protocol/pyproject.toml",
    "flow-corpus/pyproject.toml",
)

_COVERAGE_SOURCE_NOTICE = 'echo "quality-gate: COVERAGE_SOURCE is ignored; targets are fixed at generation time"'
_COV_FAIL_UNDER_NOTICE = 'echo "quality-gate: COV_FAIL_UNDER is ignored; targets are fixed at generation time"'
_PYTEST_ADDOPTS_NOTICE = 'echo "quality-gate: PYTEST_ADDOPTS is ignored; this stage is a gate and has no opt-out"'

# The pre-hardening forms: a live env reference interpolated straight into the pytest-cov
# invocation. Their presence anywhere in a regenerated script is the exact evasion this
# feature closed -- COV_FAIL_UNDER=0 (or a narrow COVERAGE_SOURCE) made the gate trivially
# pass. Multi-source scripts never contained the COVERAGE_SOURCE form to begin with (they use
# per-source --cov= literals), so a clean absence check is correct for all 7 either way.
_RAW_COV_FAIL_UNDER = '--cov-fail-under="$COV_FAIL_UNDER"'
_RAW_COVERAGE_SOURCE = '--cov="$COVERAGE_SOURCE"'

# The anchored form AS IT APPEARS IN THE RAW FILE TEXT (this is a plain-text read, not a TOML
# parse): TOML basic-string escaping doubles each backslash, so the committed source reads
# "^\\s*\\.\\.\\.$" (two literal backslashes before each regex metacharacter), which a TOML
# parser turns into the single-backslash regex "^\s*\.\.\.$" that coverage.py actually uses.
# The raw (r'...') Python literal below matches the file's bytes, not the parsed value.
_ANCHORED_PATTERN = r'"^\\s*\\.\\.\\.$"'


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    for rel_path in _GATE_SCRIPTS:
        gate = _read(rel_path)

        _check(
            _COVERAGE_SOURCE_NOTICE in gate,
            f"{rel_path}: warns when a live COVERAGE_SOURCE override is ignored",
            errors,
        )
        _check(
            _COV_FAIL_UNDER_NOTICE in gate,
            f"{rel_path}: warns when a live COV_FAIL_UNDER override is ignored",
            errors,
        )
        _check(
            _PYTEST_ADDOPTS_NOTICE in gate,
            f"{rel_path}: warns when a live PYTEST_ADDOPTS override is ignored",
            errors,
        )
        _check(
            _RAW_COV_FAIL_UNDER not in gate,
            f"{rel_path}: --cov-fail-under is a generation-time literal, not $COV_FAIL_UNDER",
            errors,
        )
        _check(
            _RAW_COVERAGE_SOURCE not in gate,
            f"{rel_path}: --cov= is a generation-time literal, not $COVERAGE_SOURCE",
            errors,
        )

        # Every do_test/do_coverage pair clears PYTEST_ADDOPTS before invoking pytest; root's
        # hand-maintained do_extra() (below the marker) adds a third, hand-kept occurrence.
        expected_unsets = 3 if rel_path == "scripts/quality-gate.sh" else 2
        actual_unsets = gate.count("unset PYTEST_ADDOPTS")
        _check(
            actual_unsets >= expected_unsets,
            f"{rel_path}: expected >= {expected_unsets} 'unset PYTEST_ADDOPTS' occurrences, found {actual_unsets}",
            errors,
        )

    for rel_path in _ANCHORED_REGEX_PYPROJECTS:
        pyproject = _read(rel_path)
        _check(
            _ANCHORED_PATTERN in pyproject,
            f"{rel_path}: exclude_also carries the anchored ellipsis-stub pattern {_ANCHORED_PATTERN}",
            errors,
        )

    return report(logger, "F-054", errors)


if __name__ == "__main__":
    sys.exit(main())
