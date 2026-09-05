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
    # The evaluation DATA, not just the code that reads it. `config/testgen_eval.yaml`
    # points its dataset straight at `corpora/testgen/v1/eval/`, so swapping the corpus for
    # an easier one moves every score in that matrix without touching a scorer, a threshold
    # or a gate rule -- the cheapest possible way to make a failing eval pass, and the exact
    # class of change this list exists to require a human for. It also fixes a reachability
    # hole: `corpora/**` appeared in no workflow `paths:` filter either, so a corpus-only
    # pull request ran ZERO workflows while all seven required-check stubs reported green.
    "corpora/**",
    "src/eval_harness/gating/**",
    "src/eval_harness/scorers/**",
    "src/eval_harness/judges/**",
    "tests/**",
    # "tests/**" only matches the root suite (^tests/.*$ once compiled) -- the sibling
    # packages' own test suites, including their copies of the public-surface compat guard,
    # live under these separate roots and need their own entries.
    "agent-core/tests/**",
    "behavioral-regression/tests/**",
    "flow-corpus/tests/**",
    "flow-protocol/tests/**",
    # claude-foundation/ is structurally identical to the four packages above (own
    # pyproject.toml, Makefile, isolated CI, own tests/) and was missed by the sweep that
    # added them -- its tests/test_eval_gate.py directly exercises an eval-integrity gate
    # (foundation_tools.eval_gate) and was unprotected until this entry.
    "claude-foundation/tests/**",
    ".github/**",
    # The architecture manifest is the airgap's enforcement surface: editing its
    # declared component edges could quietly let the corpus and harness import each
    # other. Treat edge changes as eval-integrity changes requiring human review.
    "architecture.yaml",
    # Gate THRESHOLDS, and the manifest that pins them. Everything above protects files
    # that *define* a gate; none of them covered the files where the gate's number lives.
    # A PR lowering `fail_under = 96` to 50 in pyproject.toml and the matching
    # `--cov-fail-under=` in the gate script passed every check here, with no label and no
    # code owner: check_charter_invariants only asserts a floor *exists*, and
    # test_e2e_matrix only asserts two anchors state the *same* number, not which.
    # coverage-floors.yaml is the declarative pin (scripts/check_coverage_floors.py
    # enforces it); the rest are the files it reads.
    "coverage-floors.yaml",
    "pyproject.toml",
    "scripts/quality-gate.sh",
    "scripts/.coveragerc",
    # Each sibling package states its own floor twice, in the same two places.
    "agent-core/pyproject.toml",
    "agent-core/scripts/quality-gate.sh",
    "behavioral-regression/pyproject.toml",
    "behavioral-regression/scripts/quality-gate.sh",
    "flow-corpus/pyproject.toml",
    "flow-corpus/scripts/quality-gate.sh",
    "flow-protocol/pyproject.toml",
    "flow-protocol/scripts/quality-gate.sh",
    "claude-foundation/pyproject.toml",
    "claude-foundation/scripts/quality-gate.sh",
    # The Makefiles that INVOKE those gates. Pinning a floor's value protects the
    # number and nothing else: every package's CI delegates through `make check`,
    # so replacing a `check:` recipe body with `@echo 'ok'` disables the gate
    # while leaving `--cov-fail-under` untouched — greener, quieter and cheaper
    # than editing the number this list already guards. `coverage-floors.yaml`
    # cannot see it, because the manifest describes declarations, not invocation.
    "Makefile",
    "agent-core/Makefile",
    "behavioral-regression/Makefile",
    "flow-corpus/Makefile",
    "flow-protocol/Makefile",
    "claude-foundation/Makefile",
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
