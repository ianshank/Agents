#!/usr/bin/env python3
"""Assert the eval-integrity guard can actually *see* every path it protects.

``scripts/eval_protected_paths.py`` declares which paths require the
``eval-change-approved`` label. ``.github/workflows/quality-gates.yml`` decides which
pull requests run the guard at all, via its ``on.pull_request.paths`` filter. Those are
two lists that must agree, and nothing asserted that they did — so they drifted: at the
time this guard was written, **9 of 15 protected patterns could not trigger it**,
including ``architecture.yaml``, which is protected precisely because editing its declared
component edges could quietly dissolve the ``eval_harness`` / ``flow_corpus`` airgap.

A protected path the workflow never fires on is not protected. This closes the loop the
same way the repo already closes it for the architecture manifest and the public-surface
baselines: by making the drift itself a CI failure.

``PROTECTED_PATTERNS`` is *imported*, never restated here — a second copy would recreate
exactly the divergence this exists to prevent. Glob translation reuses that module's
``_glob_to_regex`` for the same reason.

Usage::

    python scripts/check_guard_reachability.py            # human-readable report
    python scripts/check_guard_reachability.py --json     # machine-readable
    python scripts/check_guard_reachability.py --verbose  # debug logging

Exit codes:
    0 - every protected pattern is reachable
    1 - at least one protected pattern cannot trigger the guard
    2 - usage error (workflow missing/unparseable)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _cli import configure_logging  # noqa: E402
from eval_protected_paths import PROTECTED_PATTERNS, _glob_to_regex  # noqa: E402

logger = logging.getLogger(__name__)


class GuardNotInvokedError(RuntimeError):
    """The workflow under inspection never executes the protected-path guard."""


#: The workflow that invokes the protected-path guard. Single-sourced here rather than at
#: call sites so relocating the job is a one-line change.
GUARD_WORKFLOW = Path(".github/workflows/quality-gates.yml")

#: The script whose invocation marks a workflow as *the* guard job. If the guard moves to
#: another workflow, this is what finds it.
GUARD_SCRIPT = "check_protected_changes.py"

#: Probe leaves used to test whether a directory pattern is covered. There is more than
#: one on purpose, and they differ in *depth* as well as name.
#:
#: A single probe is not enough, and the failure is a false GREEN. With only
#: ``sample/probe.py``, the narrowed filter ``config/sample/**`` matches the probe and so
#: reports the protected pattern ``config/**`` as reachable — while a PR touching
#: ``config/other.yaml`` runs no guard at all. Requiring a filter to match every probe,
#: including a direct child and a differently-named subtree, rejects that filter.
_SAMPLE_LEAVES = ("probe.py", "sample/probe.py", "other/deep/leaf.txt")


@dataclass(frozen=True)
class Coverage:
    """Whether one protected pattern can trigger the guard, and via which filter."""

    pattern: str
    samples: tuple[str, ...]
    covering_filter: str | None

    @property
    def reachable(self) -> bool:
        return self.covering_filter is not None


def sample_paths_for(pattern: str) -> tuple[str, ...]:
    """Concrete paths that the protected *pattern* matches, spanning its breadth.

    Exact file patterns (``features.yaml``) are already concrete and yield themselves.
    Directory patterns (``tests/**``) yield several leaves at different depths, so a
    filter is only credited with covering the pattern when it matches *all* of them.

    This is a breadth probe, not a proof of language containment: it demonstrates that a
    filter fails to cover the pattern, and treats matching every probe as covering it.
    For the grammar actually in ``PROTECTED_PATTERNS`` — exact paths and ``prefix/**``
    trees — that distinction does not arise, and the probes are chosen to make any
    narrowed child filter fail.
    """
    if "*" not in pattern:
        return (pattern,)
    return tuple(pattern.replace("**", leaf).replace("//", "/") for leaf in _SAMPLE_LEAVES)


def sample_path_for(pattern: str) -> str:
    """The first probe path for *pattern* — kept for single-path callers and reporting."""
    return sample_paths_for(pattern)[0]


def filter_matches(path: str, glob: str) -> bool:
    """Whether a GitHub Actions ``paths:`` *glob* selects *path*.

    Reuses ``eval_protected_paths._glob_to_regex`` so this agrees with the guard's own
    matching by construction rather than by a second implementation that could diverge.
    """
    return bool(_glob_to_regex(glob).match(path))


def extract_path_filters(workflow_text: str) -> list[str]:
    """The ``on.pull_request.paths`` globs from a workflow, in declaration order.

    Deliberately a narrow text scan rather than a YAML load: the check must run with no
    third-party dependency (``scripts/`` has no pyyaml floor), and the ``paths:`` block is
    a flat list of quoted scalars. Comment lines and the ``paths-ignore`` key are skipped.
    """
    section = workflow_text.split("pull_request:", 1)
    if len(section) < 2:
        return []
    body = section[1]
    # Stop at the next top-level `on:` key (workflow_dispatch, schedule, push...) or at
    # the jobs block, so filters from a different trigger are never counted.
    for terminator in ("\njobs:", "\n  workflow_dispatch", "\n  schedule", "\n  push:"):
        body = body.split(terminator, 1)[0]
    if "paths:" not in body:
        return []
    block = body.split("paths:", 1)[1]
    globs: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^-\s*["\']?([^"\'\s]+)["\']?\s*$', stripped)
        if not match:
            break  # left the list
        globs.append(match.group(1))
    return globs


def script_is_invoked(workflow_text: str, script: str) -> bool:
    """Whether a workflow actually *executes* *script*, rather than merely mentioning it.

    A bare ``script in text`` search is satisfied by a comment — and this repo's
    workflows comment on their own gate scripts extensively, so that search proves
    nothing. Requires the name to appear on a non-comment line that is a ``run:`` step
    or a continuation of one (multi-line ``run: >-`` blocks).

    Shared with ``check_charter_invariants.check_quality_gates_wired``, which had the
    same substring weakness, so one definition of "wired into CI" serves both.
    """
    run_indent: int | None = None  # indentation of the `run:` key we are inside, if any
    for raw in workflow_text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if run_indent is not None and indent <= run_indent:
            run_indent = None  # dedented out of the run block
        if re.search(r"(^|\s)run:", stripped):
            run_indent = indent
            if script in stripped:
                return True
            continue
        if run_indent is not None and script in stripped:
            return True  # a continuation line of a `run: >-` or `run: |` block
    return False


def guard_is_invoked(workflow_text: str) -> bool:
    """Whether the workflow actually executes the protected-path guard."""
    return script_is_invoked(workflow_text, GUARD_SCRIPT)


def analyse(repo_root: Path, workflow: Path = GUARD_WORKFLOW) -> tuple[list[Coverage], list[str]]:
    """Map every protected pattern to the filter that covers it, if any.

    Raises ``GuardNotInvokedError`` when the workflow does not run the guard at all.
    That has to be fail-closed: with the guard job deleted but the ``paths:`` filter left
    broad, every pattern still looks "reachable" and the check reports OK — a green tick
    for a guard that no longer exists, which is the precise failure this script was
    written to prevent.
    """
    path = repo_root / workflow
    if not path.is_file():
        raise FileNotFoundError(f"guard workflow not found: {path.as_posix()}")
    text = path.read_text(encoding="utf-8")
    if not guard_is_invoked(text):
        raise GuardNotInvokedError(
            f"{workflow.as_posix()} does not run {GUARD_SCRIPT} — "
            "the guard is not invoked, so no path filter can make it fire"
        )
    filters = extract_path_filters(text)
    logger.debug("found %d pull_request path filter(s): %s", len(filters), filters)

    coverages: list[Coverage] = []
    for pattern in PROTECTED_PATTERNS:
        samples = sample_paths_for(pattern)
        # Every probe must match: a filter covering only part of the protected subtree
        # leaves the rest unguarded, which is indistinguishable from no filter at all.
        covering = next((f for f in filters if all(filter_matches(s, f) for s in samples)), None)
        logger.debug("pattern %-32s samples %-52s -> %s", pattern, samples, covering or "UNREACHABLE")
        coverages.append(Coverage(pattern=pattern, samples=samples, covering_filter=covering))
    return coverages, filters


def render_text(coverages: list[Coverage], filters: list[str]) -> str:
    unreachable = [c for c in coverages if not c.reachable]
    lines: list[str] = []
    if unreachable:
        lines.append(
            f"guard-reachability: FAIL - {len(unreachable)} of {len(coverages)} protected pattern(s) cannot trigger the guard:"
        )
        for c in unreachable:
            uncovered = [s for s in c.samples if not any(filter_matches(s, f) for f in filters)]
            example = (uncovered or list(c.samples))[0]
            lines.append(f"  - {c.pattern}  (a PR touching only {example} runs no protected-path check)")
        lines.append("")
        lines.append(f"  Current pull_request paths filters: {filters}")
        lines.append("  Fix: widen the filter in .github/workflows/quality-gates.yml to cover these paths.")
    else:
        lines.append(
            f"guard-reachability: OK - all {len(coverages)} protected pattern(s) reachable via {len(filters)} filter(s)."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=".", help="repository root (default: cwd)")
    parser.add_argument("--workflow", default=str(GUARD_WORKFLOW), help="workflow that runs the guard")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    try:
        coverages, filters = analyse(Path(args.repo).resolve(), Path(args.workflow))
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        print(f"guard-reachability: usage error - {exc}", file=sys.stderr)
        return 2
    except GuardNotInvokedError as exc:
        # A failure, not a usage error: the guard being absent is exactly the condition
        # this gate exists to catch, and must never exit 0.
        logger.error("%s", exc)
        print(f"guard-reachability: FAIL - {exc}")
        return 1

    unreachable = [c for c in coverages if not c.reachable]
    if args.json:
        # Sorted so the payload is byte-stable for a given input and safe to diff.
        print(
            json.dumps(
                {
                    "passed": not unreachable,
                    "filters": filters,
                    "coverage": sorted((asdict(c) for c in coverages), key=lambda c: c["pattern"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text(coverages, filters))

    if unreachable:
        logger.error("%d protected pattern(s) unreachable", len(unreachable))
    return 1 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
