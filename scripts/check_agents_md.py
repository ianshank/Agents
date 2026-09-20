#!/usr/bin/env python3
"""CI guard: keep the per-directory ``AGENTS.md`` set complete, small, and honest.

Coding agents read the ``AGENTS.md`` nearest the file they are editing. Nesting keeps
instruction budget low -- a subdirectory's file costs nothing until an agent works there --
but only while each file stays small and local. This guard enforces that bargain:

  1. Coverage   - every directory in the tier table has a file; every directory recorded as
                  covered-by-parent does not. A missing file reads as a decision, not a gap.
  2. Budget     - line count within the tier ceiling (the Context Bloat heuristic).
  3. Sections   - the template's headings, present and in order.
  4. Mermaid    - fences close, declare ``accTitle``/``accDescr``, and stay ASCII so GitHub
                  renders them.
  5. Links      - every relative link resolves from the file's own directory.
  6. Lint leak  - style rules ruff/mypy already enforce are rejected as dead weight.
  7. Blind ref  - a "See also" row citing a path with no "Read it when" trigger fails.

The tier table lives in ``scripts/_agents_md_lib.py``; this module is the CLI around it.

Usage:

  python scripts/check_agents_md.py                # check the whole repo
  python scripts/check_agents_md.py --root PATH    # check another checkout
  python scripts/check_agents_md.py --json         # machine-readable findings
  python scripts/check_agents_md.py --paths-only   # just the offending files, for xargs

Exit codes:
    0 - every AGENTS.md is present, in budget, and well formed
    1 - at least one violation
    2 - configuration / usage error (root missing, or a file unreadable / not UTF-8)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from _agents_md_lib import collect_findings, required_dirs  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the per-directory AGENTS.md set.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", default=".", help="repo root to check (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument(
        "--paths-only", action="store_true", help="print only offending paths"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )

    root = Path(args.root)
    if not root.is_dir():
        print(
            f"agents-md: usage error - no such directory: {root.as_posix()}",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    findings = collect_findings(root)

    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, sort_keys=True))
    elif args.paths_only:
        for path in sorted({f.path for f in findings}):
            print(path)
    elif findings:
        print(f"agents-md: FAIL - {len(findings)} violation(s):")
        for finding in findings:
            print(finding.render())
    else:
        print(
            f"agents-md: OK - {len(required_dirs()) + 1} files present, in budget, well formed."
        )

    if any(f.check == "read" for f in findings):
        logger.warning("agents-md: unreadable/non-UTF-8 file(s)")
        return EXIT_USAGE_ERROR
    if findings:
        logger.warning("agents-md: %d violation(s)", len(findings))
        return EXIT_VIOLATION
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
