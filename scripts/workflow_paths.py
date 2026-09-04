#!/usr/bin/env python3
"""Decide which workflows a set of changed files triggers.

``.github/workflows/required-check-stubs.yml`` needs this to know whether to post
a stub check for a workflow the ``paths:`` filter skipped. It originally carried
a hand-rolled YAML reader inline in the workflow, which had two properties that
made it the wrong place for this logic:

* **It could be wrong rather than loud.** A trailing comment on a list item
  (``- "tests/**"  # only the tests``) or a glob containing a space failed its
  item regex, which ``break``-ed out of the list and silently returned a
  *truncated* set of globs. Fewer globs means "the real workflow did not run",
  so the stub ran green *beside* the real job — the duplicate-context false green
  the stub mechanism exists to prevent. GitHub's ``!`` negation was likewise read
  as a literal character, inverting a filter's meaning.
* **It could never be tested.** Code embedded in a workflow's ``run:`` block is
  invisible to pytest and to every coverage gate in this repository.

So the parsing is not fixed here, it is deleted: ``yaml.safe_load`` reads the
workflow, which is the same parser GitHub itself uses. What remains is the glob
translation and the trigger decision, both of which are ordinary testable
functions.

Usage::

    python scripts/workflow_paths.py --changed-files changed.txt \\
        --workflow quality_gates=.github/workflows/quality-gates.yml
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any, Final

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(_HERE))

from _cli import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

#: Exit code for a usage/config error, matching the sibling guards.
EXIT_USAGE_ERROR: Final[int] = 2

#: YAML 1.1 resolves the bare key ``on:`` to the boolean ``True`` (the "Norway
#: problem"). Accept either so this does not depend on the loader's resolver.
_ON_KEYS: Final[tuple[object, ...]] = ("on", True)


class WorkflowPathsError(ValueError):
    """A workflow could not be read, or declares a filter this cannot model.

    Raised rather than defaulted: every failure mode here resolves to "the real
    workflow did not run", which posts a stub for a job that may in fact be
    running. A loud red gate is recoverable; a silent duplicate green is not.
    """


def pull_request_paths(workflow: Path) -> list[str]:
    """The ``on.pull_request.paths:`` globs of *workflow*, in declaration order."""
    try:
        document: Any = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowPathsError(f"{workflow}: cannot be read as YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise WorkflowPathsError(f"{workflow}: top level is not a mapping")

    triggers = next((document[key] for key in _ON_KEYS if key in document), None)
    if not isinstance(triggers, dict):
        raise WorkflowPathsError(f"{workflow}: no `on:` trigger mapping")

    pull_request = triggers.get("pull_request")
    if not isinstance(pull_request, dict):
        raise WorkflowPathsError(f"{workflow}: no `pull_request:` trigger")

    globs = pull_request.get("paths")
    if not isinstance(globs, list) or not globs:
        raise WorkflowPathsError(f"{workflow}: `pull_request.paths` is missing or empty")

    resolved = [str(g) for g in globs]
    negated = [g for g in resolved if g.startswith("!")]
    if negated:
        # GitHub's negation flips a filter's meaning, and modelling it wrongly
        # would silently invert this gate's answer for that workflow.
        raise WorkflowPathsError(f"{workflow}: negated path filter(s) {negated} are not supported")
    return resolved


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Translate one GitHub path filter into an anchored regex.

    GitHub's semantics, which differ from :mod:`fnmatch`: ``**`` spans ``/``
    while ``*`` and ``?`` do not.
    """
    out: list[str] = []
    index = 0
    while index < len(glob):
        if glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def workflow_runs(workflow: Path, changed_files: list[str]) -> bool:
    """Whether *workflow* is triggered by *changed_files*.

    GitHub runs a ``paths:`` workflow when **at least one** changed file matches.
    """
    matchers = [glob_to_regex(g) for g in pull_request_paths(workflow)]
    hit = next((f for f in changed_files if any(m.match(f) for m in matchers)), None)
    logger.info("%s: %s (e.g. %s)", workflow, "RUNS" if hit else "does not run", hit or "-")
    return hit is not None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--changed-files", required=True, help="File holding one changed path per line")
    parser.add_argument(
        "--workflow",
        action="append",
        required=True,
        metavar="KEY=PATH",
        help="Output key and the workflow file it names; repeatable",
    )
    parser.add_argument("--output", default=None, help="File to append 'key=true|false' lines to")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(verbose=args.verbose)

    changed = [
        line.strip() for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    lines: list[str] = []
    for entry in args.workflow:
        key, _, raw_path = entry.partition("=")
        if not key or not raw_path:
            logger.error("--workflow expects KEY=PATH, got %r", entry)
            return EXIT_USAGE_ERROR
        try:
            runs = workflow_runs(Path(raw_path), changed)
        except WorkflowPathsError as exc:
            logger.error("%s", exc)
            return EXIT_USAGE_ERROR
        lines.append(f"{key}={'true' if runs else 'false'}")

    if args.output:
        with Path(args.output).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
