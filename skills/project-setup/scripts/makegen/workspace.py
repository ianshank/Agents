"""Workspace (monorepo) detection for the project-setup skill.

A workspace member is an IMMEDIATE child directory of the root that contains its own
``pyproject.toml``. The immediate-child rule is load-bearing: it deterministically excludes
nested trees (e.g. ``skills/*/evals/fixtures/*/pyproject.toml``) with no exclude list.
Membership is a pure, sorted filesystem observation — sorting exists solely for byte-stable
output (fan-out targets and recipes render in a fixed order); no dependency ordering is
implied, because every emitted aggregate delegates per member via ``$(MAKE) -C <member>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Member names must be usable verbatim as Make target suffixes (check-<member>) and as the
# directory argument of `$(MAKE) -C <member>`. Anything else (spaces, ':', '$', ...) is
# skipped rather than emitted broken — the caller surfaces skipped names so the omission is
# visible, never silent.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Names whose <verb>-<member> targets would collide with the generated aggregates
# (check-all / install-all / clean-all). GNU Make treats duplicate standard rules as
# "last recipe wins" with a warning, silently dropping the member's own delegation — so a
# member directory named `all` is skipped (reported) rather than emitted broken.
_RESERVED_NAMES = frozenset({"all"})


@dataclass(frozen=True)
class WorkspaceFacts:
    """Immediate-child package members of a monorepo root (sorted, byte-stable)."""

    members: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()  # member-like dirs whose names are not Make/pip-safe

    @property
    def is_workspace(self) -> bool:
        """True when at least one member exists (else workspace mode has nothing to add)."""
        return bool(self.members)


def detect_workspace(root: Path | str) -> WorkspaceFacts:
    """Return the workspace members of ``root``.

    Hidden directories (leading dot) are never members: they are tool/VCS state by
    convention, not packages.
    """
    root = Path(root)
    if not root.is_dir():
        return WorkspaceFacts()
    members: list[str] = []
    skipped: list[str] = []
    for child in sorted(root.iterdir()):
        # Symlinked directories are excluded: a link could point outside the tree (or back
        # into it), and `$(MAKE) -C` into such a member would escape the workspace.
        if not child.is_dir() or child.is_symlink() or child.name.startswith("."):
            continue
        if not (child / "pyproject.toml").is_file():
            continue
        if _SAFE_NAME.fullmatch(child.name) and child.name not in _RESERVED_NAMES:
            members.append(child.name)
        else:
            skipped.append(child.name)
    return WorkspaceFacts(members=tuple(members), skipped=tuple(skipped))
