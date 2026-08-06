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

#: The workflow that invokes the protected-path guard. Single-sourced here rather than at
#: call sites so relocating the job is a one-line change.
GUARD_WORKFLOW = Path(".github/workflows/quality-gates.yml")

#: The script whose invocation marks a workflow as *the* guard job. If the guard moves to
#: another workflow, this is what finds it.
GUARD_SCRIPT = "check_protected_changes.py"

#: A representative file used to test whether a directory pattern is covered. Any path
#: under the protected subtree works; this one is arbitrary but stable.
_SAMPLE_LEAF = "sample/probe.py"


@dataclass(frozen=True)
class Coverage:
    """Whether one protected pattern can trigger the guard, and via which filter."""

    pattern: str
    sample: str
    covering_filter: str | None

    @property
    def reachable(self) -> bool:
        return self.covering_filter is not None


def sample_path_for(pattern: str) -> str:
    """A concrete path that the protected *pattern* would match.

    Directory patterns (``tests/**``) need a leaf to test against; exact file patterns
    (``features.yaml``) are already concrete.
    """
    if "*" not in pattern:
        return pattern
    return pattern.replace("**", _SAMPLE_LEAF).replace("//", "/")


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


def analyse(repo_root: Path, workflow: Path = GUARD_WORKFLOW) -> tuple[list[Coverage], list[str]]:
    """Map every protected pattern to the filter that covers it, if any."""
    path = repo_root / workflow
    if not path.is_file():
        raise FileNotFoundError(f"guard workflow not found: {path}")
    text = path.read_text(encoding="utf-8")
    if GUARD_SCRIPT not in text:
        logger.warning(
            "%s does not invoke %s — the guard may have moved; this check is looking at the wrong workflow",
            workflow,
            GUARD_SCRIPT,
        )
    filters = extract_path_filters(text)
    logger.debug("found %d pull_request path filter(s): %s", len(filters), filters)

    coverages: list[Coverage] = []
    for pattern in PROTECTED_PATTERNS:
        sample = sample_path_for(pattern)
        covering = next((f for f in filters if filter_matches(sample, f)), None)
        logger.debug("pattern %-32s sample %-40s -> %s", pattern, sample, covering or "UNREACHABLE")
        coverages.append(Coverage(pattern=pattern, sample=sample, covering_filter=covering))
    return coverages, filters


def render_text(coverages: list[Coverage], filters: list[str]) -> str:
    unreachable = [c for c in coverages if not c.reachable]
    lines: list[str] = []
    if unreachable:
        lines.append(
            f"guard-reachability: FAIL - {len(unreachable)} of {len(coverages)} protected pattern(s) cannot trigger the guard:"
        )
        for c in unreachable:
            lines.append(f"  - {c.pattern}  (a PR touching only {c.sample} runs no protected-path check)")
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
