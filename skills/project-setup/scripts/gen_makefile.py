#!/usr/bin/env python3
"""Generate a deterministic Makefile for a Python project.

  python scripts/gen_makefile.py                       # write ./Makefile for the current project
  python scripts/gen_makefile.py --root path/to/proj   # inspect a different project root
  python scripts/gen_makefile.py --stdout              # print instead of writing
  python scripts/gen_makefile.py --check               # advisory: exit 1 if the committed Makefile is stale

The generator inspects the project (``pyproject.toml`` tables, marker files, layout) and
emits a self-documenting Makefile. It never runs the model at generation time beyond this
one invocation, and the emitted file runs with zero inference thereafter.

Exit codes: 0 success (or ``--check`` up to date); 1 ``--check`` drift / missing.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from makegen import detect, render_makefile

logger = logging.getLogger("makegen")


def _check(out: Path, content: str) -> int:
    """Advisory freshness check: compare the committed file against a fresh render."""
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing; run the project-setup skill to create it")
        return 1
    if out.read_text(encoding="utf-8") == content:
        print(f"{out.as_posix()} is up to date")
        return 0
    print(f"[drift] {out.as_posix()} is stale; regenerate with the project-setup skill")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic Makefile for a Python project.")
    parser.add_argument("--root", default=".", help="Project root to inspect (default: current directory).")
    parser.add_argument("--out", default=None, help="Output path (default: <root>/Makefile).")
    parser.add_argument("--stdout", action="store_true", help="Print the Makefile instead of writing it.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Advisory: exit 1 if the committed Makefile differs from a fresh render.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging (prints detected facts).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    root = Path(args.root)
    facts = detect(root)
    logger.debug("detected facts for %s: %s", root.as_posix(), facts)
    content = render_makefile(facts)

    if args.stdout:
        sys.stdout.write(content)
        return 0

    out = Path(args.out) if args.out else root / "Makefile"
    if args.check:
        return _check(out, content)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {out.as_posix()} ({facts.package_manager} project)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
