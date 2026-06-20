#!/usr/bin/env python3
"""Single source of truth for the eval-integrity protected path set.

This harness *evaluates* things. The cheapest way to make a failing eval "pass"
is not to fix code but to weaken the evaluation itself — lower a gate threshold,
swap to the deterministic mock judge, loosen a scorer, or edit a ``verification``
clause. These paths define the evaluation surface and therefore must only ever be
changed by a human, never by an automated fix step, and only under explicit review.

The set is exported here so every enforcement point (the CI guard, the disabled
auto-fix loop's scope guard, and the tests) shares one definition.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Ordered, documented protected globs. ``**`` matches across path separators;
# ``*`` matches within a single segment.
PROTECTED_PATTERNS: tuple[str, ...] = (
    "features.yaml",
    "features.schema.json",
    "scripts/validations/**",
    "config/**",
    "src/eval_harness/gating/**",
    "src/eval_harness/scorers/**",
    "src/eval_harness/judges/**",
    "tests/**",
    ".github/**",
    # The architecture manifest is the airgap's enforcement surface: editing its
    # declared component edges could quietly let the corpus and harness import each
    # other. Treat edge changes as eval-integrity changes requiring human review.
    "architecture.yaml",
)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob (with ``**``/``*``/``?``) into an anchored regex."""
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


_COMPILED: tuple[re.Pattern[str], ...] = tuple(_glob_to_regex(p) for p in PROTECTED_PATTERNS)


def _normalise(path: str) -> str:
    """Normalise a path for matching: forward slashes, no leading ``./`` or ``/``."""
    norm = path.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm.lstrip("/")


def is_protected(path: str) -> bool:
    """Return True if *path* matches any protected pattern."""
    norm = _normalise(path)
    return any(rx.match(norm) for rx in _COMPILED)


def matched_protected(paths: Iterable[str]) -> list[str]:
    """Return the normalised subset of *paths* that are protected, sorted + de-duplicated.

    Paths are normalised before de-duplication so equivalent spellings (``./features.yaml``
    vs ``features.yaml``, mixed separators) collapse to a single, stable entry regardless
    of how the caller formatted them.
    """
    return sorted({_normalise(p) for p in paths if is_protected(p)})
