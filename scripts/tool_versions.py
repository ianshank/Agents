#!/usr/bin/env python3
"""Single source of truth for the ruff/mypy versions pinned across the fleet.

``ruff``/``mypy`` are pinned (not floored with ``>=``) in the ``dev`` extra of every
package's ``pyproject.toml`` so local and CI lint/format/type-check identically — an
unpinned ruff drifted once already (0.8.0 local vs 0.15.20 CI) and broke
``ruff format --check`` (see ``AGENTS.md`` "Non-negotiable constraints"). The same two
versions are hand-duplicated into the ``dev`` extra of 7 ``pyproject.toml`` files (root,
``agent-core``, ``behavioral-regression``, ``flow-protocol``, ``flow-corpus``,
``claude-foundation``, ``experiments/backend-validation``) and into 9 ``pip install``
lines in ``.github/workflows/skills-ci.yml``. This module is the one place a version is
typed; every other copy is checked against it rather than against each other.

Bump ``RUFF_VERSION``/``MYPY_VERSION`` here first, then propagate the identical values
to every ``pyproject.toml`` dev extra and every ``skills-ci.yml`` pip-install line by
hand — deliberately, in lockstep, per ADR 0034. This module does not install, invoke,
or otherwise act on the pins; it only names them.

Enforced by: ``scripts/validations/F_054.py`` (read-only; asserts every copy matches).
"""

from __future__ import annotations

# Bump deliberately, in lockstep with every consumer named above — CI/local skew broke
# ``ruff format --check`` once already. scripts/validations/F_054.py fails the moment
# any consumer disagrees with either value.
RUFF_VERSION = "0.15.20"
MYPY_VERSION = "2.1.0"
