#!/usr/bin/env python3
"""Generate a deterministic quality-gate shell script for a Python project.

  python scripts/gen_gate.py                       # write ./scripts/quality-gate.sh
  python scripts/gen_gate.py --root path/to/proj   # inspect a different project root
  python scripts/gen_gate.py --stdout              # print instead of writing
  python scripts/gen_gate.py --check               # advisory: exit 1 if the committed script is stale
  python scripts/gen_gate.py --print-ci            # print a CI step that runs the same script

The emitted ``quality-gate.sh`` is the single source of truth for the project's checks; CI
and ``make check`` both call it, so local and CI never drift. It runs with zero inference.

Exit codes: 0 success (or ``--check`` up to date); 1 ``--check`` drift / missing.
"""

from __future__ import annotations

import argparse
import logging
import stat
import sys
from pathlib import Path

from gategen import detect, render_ci_snippet, render_gate

logger = logging.getLogger("gategen")


def _check(out: Path, content: str) -> int:
    """Advisory freshness check: compare the committed script against a fresh render."""
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing; run the quality-gate skill to create it")
        return 1
    if out.read_text(encoding="utf-8") == content:
        print(f"{out.as_posix()} is up to date")
        return 0
    print(f"[drift] {out.as_posix()} is stale; regenerate with the quality-gate skill")
    return 1


def _make_executable(path: Path) -> None:
    """chmod +x (u+g+o) so the script can be run directly; mode is not file content."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic quality-gate script.")
    parser.add_argument("--root", default=".", help="Project root to inspect (default: current directory).")
    parser.add_argument("--out", default=None, help="Output path (default: <root>/scripts/quality-gate.sh).")
    parser.add_argument("--stdout", action="store_true", help="Print the script instead of writing it.")
    parser.add_argument("--check", action="store_true", help="Advisory: exit 1 if the committed script is stale.")
    parser.add_argument("--print-ci", action="store_true", help="Print a CI step that runs the same script, then exit.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging (prints detected facts).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.print_ci:
        sys.stdout.write(render_ci_snippet())
        return 0

    root = Path(args.root)
    facts = detect(root)
    logger.debug("detected facts for %s: %s", root.as_posix(), facts)
    content = render_gate(facts)

    if args.stdout:
        sys.stdout.write(content)
        return 0

    out = Path(args.out) if args.out else root / "scripts" / "quality-gate.sh"
    if args.check:
        return _check(out, content)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")
    _make_executable(out)
    if not facts.has_any_step:
        print(f"[warn] no checks detected in {root.as_posix()} - wrote a no-op gate", file=sys.stderr)
    print(f"wrote {out.as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
