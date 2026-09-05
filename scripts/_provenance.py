#!/usr/bin/env python3
"""Git provenance for the feature ledger: does a recorded commit exist, and did it land?

Extracted from ``validate.py`` when the ancestry check pushed that file past the 500-line
hard budget (``scripts/check_size_budget.py``). The split follows the house precedent for
that gate — ADR 0036's ``engine.py`` -> ``core/_execution_strategies.py`` and ADR 0019's
``store_sync/`` package split — moving a cohesive concern to its own owner rather than
trimming documentation to fit. ``scripts/_cli.py`` and ``scripts/_config.py`` are the
existing private-helper-module precedent in this directory.

The concern is cohesive because both questions are about the same object and are answered
with the same tool, but they are *different questions*:

    resolve  -- "is this a commit?"      -> catches a rebase orphan, a deleted branch, a typo
    ancestry -- "did this commit land?"  -> catches a ref on a branch that never merged

A resolution check alone reports the second case as healthy. CI clones with
``fetch-depth: 0``, which fetches every branch, so an unmerged branch's commit resolves
perfectly. Before this module the repository's only defence against that was a convention
in a YAML comment (``.github/workflows/quality-gates.yml``: "Squash-merging a PR would rot
its own ref, so keep merge commits"), and one ref had already slipped past it undetected
for six weeks.

Every function here is import-safe and side-effect free: ``run_git`` is the single choke
point for subprocess use, and it returns ``None`` rather than raising when git is absent.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ANCESTRY_REF",
    "GIT_MISSING_MESSAGE",
    "check_refs",
    "is_shallow_clone",
    "ref_problem",
    "run_git",
]

#: Revision every ``implemented_in`` ref must be an ancestor of.
#:
#: ``HEAD``, deliberately, and not ``origin/main``. A pull request that stamps its own
#: feature's SHA records a commit on its own branch, which is not on ``main`` yet;
#: measured against ``origin/main`` that legitimate case fails and the check needs an
#: exemption list for refs the current diff introduces. Against ``HEAD`` both cases fall
#: out with no exemptions: CI checks out the PR's merge commit on ``pull_request`` (whose
#: parents are the base and the PR head, so a stamp on either is an ancestor) and ``main``
#: itself on ``push``.
#:
#: Deliberately not a CLI flag. A guard whose target the caller can retarget is a guard the
#: caller can switch off, and the point of this check is that provenance cannot be
#: asserted, only demonstrated. :func:`check_refs` takes it as a keyword argument so tests
#: can aim it at a fixture repository's revisions.
ANCESTRY_REF: str = "HEAD"

#: Reported when git itself cannot be run. Named rather than inlined because both the
#: caller and its test assert on it, and a message only one of them knows is a message
#: that drifts.
GIT_MISSING_MESSAGE: str = "Git: git is not available, so no implemented_in ref could be verified"

#: ``git merge-base --is-ancestor`` exit codes. 0 and 1 are the only *answers*; anything
#: else means the question was not answered, which this module reports rather than
#: swallows — passing a check that measured nothing is the failure it exists to prevent.
_ANCESTRY_YES: int = 0
_ANCESTRY_NO: int = 1

#: Injection seam for :func:`check_refs`, so a caller (or a test) can substitute the two
#: git-touching collaborators without monkeypatching module globals. Defaults below.
ShallowProbe = Callable[[], bool]
RefProbe = Callable[..., "str | None"]


def run_git(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a git command, or return ``None`` when git itself is unavailable.

    ``subprocess.run(["git", ...])`` raises ``FileNotFoundError`` (an ``OSError``) when git
    is not on ``PATH`` — a minimal container, a docs-only image, a sandbox. The ledger's
    other checks (schema, DAG, validation commands) need no git at all, so an absent git
    must not take the whole run down with a bare traceback. Every git call in this module
    goes through here so there is one place that can fail.
    """
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True)
    except OSError as exc:  # git missing, or not executable
        logger.debug("git unavailable (%s): %s", type(exc).__name__, exc)
        return None


def is_shallow_clone() -> bool:
    """Whether the working repository has truncated history.

    A shallow clone is missing most commits, so *every* older ``implemented_in`` ref fails
    to resolve — 30 of 50 in the clone this check was written against, none of them
    actually broken. Reporting that as provenance rot is worse than not checking: it trains
    readers to ignore the finding. Strict mode therefore downgrades itself, and says why.

    The same reasoning covers the ancestry half: reachability from ``HEAD`` is unanswerable
    once history is grafted, so a shallow clone would report every old ref as unlanded.

    Returns ``False`` when git is unavailable: "cannot tell" is not "shallow", and
    :func:`check_refs` handles the missing-git case explicitly rather than inferring it
    from this answer.
    """
    result = run_git(["rev-parse", "--is-shallow-repository"])
    return result is not None and result.returncode == 0 and result.stdout.strip() == "true"


def ref_problem(ref: str, *, ancestry_ref: str = ANCESTRY_REF) -> str | None:
    """Why *ref* is unusable as provenance, or ``None`` when it is sound.

    Three outcomes, worded apart because they have different fixes:

    *does not resolve* — the object is absent from this clone. A rebase orphan, a deleted
    squash-merged branch, or a typo. The fix is to find the commit the work landed in. The
    wording is preserved verbatim from the pre-split implementation: it is asserted on by
    an existing test and read by anyone grepping CI logs.

    *not an ancestor* — the object resolves but is unreachable from *ancestry_ref*: it is
    on a branch that never landed. Invisible to a resolution check (see the module
    docstring for why ``fetch-depth: 0`` makes that so).

    *could not be determined* — git answered neither yes nor no. Reported, not swallowed.
    """
    resolved = run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    if resolved is None or resolved.returncode != 0:
        return "does not resolve"

    ancestry = run_git(["merge-base", "--is-ancestor", ref, ancestry_ref])
    if ancestry is None:  # git vanished between two calls; nothing sound left to say
        return f"ancestry against {ancestry_ref} could not be determined (git became unavailable)"
    if ancestry.returncode == _ANCESTRY_YES:
        return None
    if ancestry.returncode == _ANCESTRY_NO:
        return f"resolves but is not an ancestor of {ancestry_ref} — it is on a branch that never landed"
    return (
        f"ancestry against {ancestry_ref} could not be determined "
        f"(git exit {ancestry.returncode}: {ancestry.stderr.strip() or 'no stderr'})"
    )


def check_refs(
    features: list[dict[str, Any]],
    *,
    strict: bool = False,
    ancestry_ref: str = ANCESTRY_REF,
    shallow_probe: ShallowProbe | None = None,
    ref_probe: RefProbe | None = None,
) -> list[str]:
    """Verify each ``implemented_in`` ref resolves *and* is part of this history.

    Parameters
    ----------
    features:
        Ledger entries. Only those carrying a truthy ``implemented_in`` are examined —
        the field is optional, so an absent ref is not a finding.
    strict:
        When *True*, ref problems are errors. When *False* (default), warnings only.
        Downgraded to warnings on a shallow clone: the refs are absent, and unreachable,
        because the history is truncated, not because the provenance is wrong. CI checks
        out with ``fetch-depth: 0``, so the strict path is the one that runs there.
    ancestry_ref:
        Revision the refs must be reachable from. Defaults to :data:`ANCESTRY_REF`.
    shallow_probe, ref_probe:
        Collaborator seams, defaulting to :func:`is_shallow_clone` and :func:`ref_problem`.
        Injection rather than monkeypatching keeps a test's substitution visible at the
        call site and independent of where these functions happen to live — the module
        split that created this file broke exactly that kind of patch elsewhere.

    A **missing git** is treated differently from a shallow clone, deliberately. A shallow
    clone is a detectable, benign reason for the data to be absent, so downgrading is
    honest. No git at all means nothing was verified — and passing a check that measured
    nothing is the exact failure this validator exists to prevent. Under strict that is an
    error; without it, a warning, since the remaining ledger checks are still worth running.
    """
    shallow = shallow_probe if shallow_probe is not None else is_shallow_clone
    probe = ref_probe if ref_probe is not None else ref_problem

    errors: list[str] = []
    refs = [f for f in features if f.get("implemented_in")]
    if refs and run_git(["rev-parse", "--git-dir"]) is None:
        if strict:
            errors.append(GIT_MISSING_MESSAGE)
            logger.error("%s (strict mode requires them verified)", GIT_MISSING_MESSAGE)
        else:
            logger.warning("%s", GIT_MISSING_MESSAGE)
        return errors
    if strict and shallow():
        logger.warning(
            "shallow clone detected - downgrading strict provenance checks to warnings; "
            "run `git fetch --unshallow` to check them for real"
        )
        strict = False

    # One probe per DISTINCT ref, not per feature: a single landing commit can carry
    # several features (five share one today) and each probe costs two subprocesses.
    verdicts: dict[str, str | None] = {}
    for feat in refs:
        ref: str = feat["implemented_in"]
        if ref not in verdicts:
            verdicts[ref] = probe(ref, ancestry_ref=ancestry_ref)
            logger.debug("provenance: %s -> %s", ref, verdicts[ref] or "ok")
        problem = verdicts[ref]
        if problem is None:
            continue
        msg = f"Git: {feat['id']} implemented_in ref '{ref}' {problem}"
        if strict:
            errors.append(msg)
            logger.error(msg)
        else:
            logger.warning(msg)
    logger.debug("provenance: %d distinct ref(s) across %d feature(s)", len(verdicts), len(refs))
    return errors
