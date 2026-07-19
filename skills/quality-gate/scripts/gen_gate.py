#!/usr/bin/env python3
"""Generate a deterministic quality-gate shell script for a Python project.

  python scripts/gen_gate.py                       # write ./scripts/quality-gate.sh
  python scripts/gen_gate.py --root path/to/proj   # inspect a different project root
  python scripts/gen_gate.py --lint-path src --lint-path tests \\
      --typecheck-path src/pkg --typecheck-path scripts   # explicit paths (repeatable)
  python scripts/gen_gate.py --stdout              # print instead of writing
  python scripts/gen_gate.py --check               # advisory: exit 1 if the committed script is stale
  python scripts/gen_gate.py --print-ci            # print a CI step that runs the same script

The emitted ``quality-gate.sh`` is the single source of truth for the project's checks; CI
and ``make check`` both call it, so local and CI never drift. It runs with zero inference.

Explicit path flags are observable generation-time inputs (recorded in the artifact's
``# regenerate:`` provenance comment, so the render is reproducible). Everything below the
hand-extension marker in an existing script is preserved on rewrite and ignored by
``--check`` (which compares only the generator-owned prefix).

Exit codes: 0 success (or ``--check`` up to date); 1 ``--check`` drift / missing.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import stat
import sys
from pathlib import Path

from gategen import MARKER, detect, render_ci_snippet, render_gate, split_at_marker

logger = logging.getLogger("gategen")


def _check(out: Path, content: str) -> int:
    """Advisory freshness check: generator-owned prefix compare + tail dispatch invariant.

    Hand content below the marker is never compared — but the tail must still contain the
    ``main "$@"`` dispatch line. Without that invariant, a gate truncated at the marker
    would define every check and run none (exit 0), while --check kept saying 'up to date'.
    """
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing; run the quality-gate skill to create it")
        return 1
    existing = out.read_text(encoding="utf-8")
    fresh_prefix, _ = split_at_marker(content)
    existing_prefix, existing_tail = split_at_marker(existing)
    if existing_prefix != fresh_prefix:
        era = "" if MARKER in existing else " (pre-marker 1.0.x artifact)"
        print(f"[drift] {out.as_posix()} is stale{era}; regenerate with the quality-gate skill")
        return 1
    if 'main "$@"' not in existing_tail:
        print(
            f'[drift] {out.as_posix()}: the main "$@" dispatch line is missing below the marker - the gate runs NOTHING'
        )
        return 1
    print(f"{out.as_posix()} is up to date (hand extensions below the marker are not checked)")
    return 0


def _make_executable(path: Path) -> None:
    """chmod +x (u+g+o) so the script can be run directly; mode is not file content."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_preserving_tail(out: Path, content: str) -> bool:
    """Write ``content``, keeping any existing hand-maintained tail below the marker.

    Returns True when an existing tail was preserved. A pre-marker (1.0.x) file has no
    seam to preserve through, so it is rewritten whole — with a loud warning, because its
    era's header invited hand edits anywhere in the file.
    """
    preserved = False
    if out.is_file():
        existing = out.read_text(encoding="utf-8")
        if MARKER in existing:
            _, existing_tail = split_at_marker(existing)
            if existing_tail:
                fresh_prefix, _ = split_at_marker(content)
                content = fresh_prefix + existing_tail
                preserved = True
        elif existing != content:
            print(
                f"[warn] {out.as_posix()} predates the hand-extension marker; rewriting the WHOLE file"
                " - any hand modifications in it are NOT preserved (recover them from version control)",
                file=sys.stderr,
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")
    _make_executable(out)
    return preserved


def _regen_args(
    args: argparse.Namespace, lint_paths: tuple[str, ...], typecheck_paths: tuple[str, ...]
) -> tuple[str, ...]:
    """Canonical, reproducible CLI form of this invocation (embedded as provenance).

    Only EFFECTIVE flags are recorded (an ignored ``--lint-path``/``--typecheck-path`` must
    not appear in provenance as if honored). Includes ``--out`` when explicitly given, so
    re-running the comment writes to the same place. Prefer relative ``--root``/``--out``
    for committed artifacts: values are embedded verbatim, and absolute paths would make
    the artifact host-specific.
    """
    parts: list[str] = ["--root", args.root]
    for path in lint_paths:
        parts += ["--lint-path", path]
    for path in typecheck_paths:
        parts += ["--typecheck-path", path]
    if args.out:
        parts += ["--out", args.out]
    return tuple(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a deterministic quality-gate script.")
    parser.add_argument("--root", default=".", help="Project root to inspect (default: current directory).")
    parser.add_argument("--out", default=None, help="Output path (default: <root>/scripts/quality-gate.sh).")
    parser.add_argument(
        "--lint-path",
        action="append",
        default=None,
        metavar="PATH",
        help="Explicit ruff path (repeatable). Default: the whole tree ('.').",
    )
    parser.add_argument(
        "--typecheck-path",
        action="append",
        default=None,
        metavar="PATH",
        help="Explicit type-check path (repeatable; multiple paths render one invocation each).",
    )
    parser.add_argument("--stdout", action="store_true", help="Print the script instead of writing it.")
    parser.add_argument("--check", action="store_true", help="Advisory: exit 1 if the committed script is stale.")
    parser.add_argument("--print-ci", action="store_true", help="Print a CI step that runs the same script, then exit.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging (prints detected facts).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.print_ci:
        sys.stdout.write(render_ci_snippet())
        return 0

    root = Path(args.root)
    facts = detect(root)
    applied_lint: tuple[str, ...] = ()
    applied_typecheck: tuple[str, ...] = ()
    if args.lint_path:
        if not facts.has_ruff:
            # Never fabricate: no detected linter means no lint step, flag or not — and an
            # ignored flag must not be recorded in provenance as if honored.
            logger.warning("ignoring --lint-path: no ruff configuration detected in %s", root.as_posix())
        else:
            applied_lint = tuple(args.lint_path)
            facts = dataclasses.replace(facts, lint_paths=applied_lint)
    if args.typecheck_path:
        if facts.type_checker is None:
            # Never fabricate: no detected type checker means no typecheck step, flag or not.
            logger.warning("ignoring --typecheck-path: no type checker detected in %s", root.as_posix())
        else:
            applied_typecheck = tuple(args.typecheck_path)
            facts = dataclasses.replace(facts, typecheck_paths=applied_typecheck)
    logger.debug("facts for %s: %s", root.as_posix(), facts)
    # The provenance program path is the generator AS INVOKED (cwd-relative, like --root),
    # so the embedded '# regenerate:' line replays from the same cwd.
    program = Path(sys.argv[0]).as_posix() if sys.argv and sys.argv[0] else "scripts/gen_gate.py"
    content = render_gate(facts, regen_args=_regen_args(args, applied_lint, applied_typecheck), regen_program=program)

    if args.stdout:
        sys.stdout.write(content)
        return 0

    out = Path(args.out) if args.out else root / "scripts" / "quality-gate.sh"
    if args.check:
        verdict = _check(out, content)
        logger.debug("--check verdict for %s: %s", out.as_posix(), "fresh" if verdict == 0 else "stale")
        return verdict

    preserved = _write_preserving_tail(out, content)
    if preserved:
        logger.debug("preserved hand-maintained tail below the marker in %s", out.as_posix())
    if not facts.has_any_step:
        print(f"[warn] no checks detected in {root.as_posix()} - wrote a no-op gate", file=sys.stderr)
    print(f"wrote {out.as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
