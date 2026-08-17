#!/usr/bin/env python3
"""Validation script for F-054 - Tool-version lockstep (ruff/mypy pins).

``ruff==0.15.20``/``mypy==2.1.0`` (current values — see ``scripts/tool_versions.py``)
are hand-duplicated across 7 ``pyproject.toml`` ``dev`` extras and 9 ``pip install``
lines in ``.github/workflows/skills-ci.yml``, each carrying a "bump deliberately, in
lockstep" comment but — before this gate — no automated check that the copies agree.
A missed bump in any one location silently drifts: green locally, red (or worse,
silently different) in CI. This asserts every occurrence of a ``ruff==``/``mypy==``
pin in those 8 files matches ``scripts/tool_versions.py`` exactly, and that every file
still carries at least one pin of each (a pin quietly dropped entirely — e.g. loosened
to ``ruff>=``  — is the same drift failure by another shape, so absence is a failure
too, not a vacuous pass; see ADR 0034 "Consequences").

Deliberately read-only: reads the text of the 7 ``pyproject.toml`` files plus
``.github/workflows/skills-ci.yml`` and runs no code, executes no subprocess, and
edits nothing. ``skills-ci.yml`` in particular is read-only by design in this change —
see ADR 0034 and ``docs/plans/orbital-drift-alignment/PLAN.md`` Phase 0 §1 (a sibling
phase edits that file; reading it here avoids any collision).

Deterministic and offline: reads files only, runs nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import re
import sys

# Ensure scripts/ and this directory are importable when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report
from tool_versions import MYPY_VERSION, RUFF_VERSION

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)

# The 7 pyproject.toml dev extras that hand-duplicate the pins (see tool_versions.py's
# module docstring for why these specific 7). Paths are relative to the repo root.
_PYPROJECT_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    "agent-core/pyproject.toml",
    "behavioral-regression/pyproject.toml",
    "flow-protocol/pyproject.toml",
    "flow-corpus/pyproject.toml",
    "claude-foundation/pyproject.toml",
    "experiments/backend-validation/pyproject.toml",
)

# Read-only: this change deliberately never writes to skills-ci.yml (see module
# docstring). A sibling phase owns edits to this file.
_SKILLS_CI_WORKFLOW = os.path.join(".github", "workflows", "skills-ci.yml")

# Matches a quoted ``ruff==X`` or ``mypy==X`` pin however it is spelled at the call
# site — a single-line TOML list entry, a multi-line TOML list entry (this pattern is
# not anchored to a line, so a pin split across lines by the *list* still has its own
# ``tool==version`` token on one line), or a double-quoted shell-word inside a YAML
# ``run:`` block — since only the token between ``==`` and the next quote/whitespace
# is captured, not the surrounding punctuation.
_PIN_PATTERN = re.compile(r"\b(ruff|mypy)==([^\"'\s]+)")

_EXPECTED: dict[str, str] = {"ruff": RUFF_VERSION, "mypy": MYPY_VERSION}


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _check_pins(text: str, label: str, errors: list[str]) -> None:
    """Assert every ruff/mypy pin found in *text* is present and matches exactly.

    Two failure modes are distinguished, both actionable on their own:
      * absence — the tool has zero pins in this file (dropped, or reworded past what
        the regex recognises — see the module docstring's parser note);
      * mismatch — a pin exists but names a version other than ``tool_versions.py``'s.
    """
    found: dict[str, list[str]] = {"ruff": [], "mypy": []}
    for tool, version in _PIN_PATTERN.findall(text):
        found[tool].append(version)

    for tool, expected_version in _EXPECTED.items():
        versions = found[tool]
        _check(
            len(versions) > 0,
            f"{label}: at least one {tool}== pin is present",
            errors,
        )
        for version in versions:
            _check(
                version == expected_version,
                f"{label}: {tool}=={version} matches tool_versions.{tool.upper()}_VERSION ({expected_version})",
                errors,
            )


def main() -> int:
    configure_logging()
    errors: list[str] = []

    for rel_path in _PYPROJECT_PATHS:
        _check_pins(_read(rel_path), rel_path, errors)

    _check_pins(_read(_SKILLS_CI_WORKFLOW), _SKILLS_CI_WORKFLOW, errors)

    return report(logger, "F-054", errors)


if __name__ == "__main__":
    sys.exit(main())
