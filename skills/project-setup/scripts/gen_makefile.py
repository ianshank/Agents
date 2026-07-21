#!/usr/bin/env python3
"""Generate a deterministic Makefile for a Python project.

  python scripts/gen_makefile.py                       # write ./Makefile for the current project
  python scripts/gen_makefile.py --root path/to/proj   # inspect a different project root
  python scripts/gen_makefile.py --workspace           # monorepo: root fan-out + one Makefile per member
  python scripts/gen_makefile.py --stdout              # print the root Makefile instead of writing
  python scripts/gen_makefile.py --check               # advisory: exit 1 if any committed artifact is stale

The generator inspects the project (``pyproject.toml`` tables, marker files, layout) and
emits a self-documenting Makefile. With ``--workspace`` it additionally detects immediate-child
member packages, appends explicit ``check-<member>`` / ``check-all`` / ``install-all`` /
``clean-all`` fan-out targets to the root Makefile, and writes each member its own Makefile
(the unchanged single-package render). ``--check`` then iterates every artifact.

Exit codes: 0 success (or ``--check`` all fresh); 1 ``--check`` any artifact stale / missing.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from makegen import detect, detect_workspace, render_makefile
from makegen.render import supports_check

logger = logging.getLogger("makegen")


def _check_one(out: Path, content: str) -> int:
    """Advisory freshness check: compare one committed file against a fresh render."""
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing; run the project-setup skill to create it")
        return 1
    if out.read_text(encoding="utf-8") == content:
        print(f"{out.as_posix()} is up to date")
        return 0
    print(f"[drift] {out.as_posix()} is stale; regenerate with the project-setup skill")
    return 1


def _write_one(out: Path, content: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8", newline="\n")


def _program() -> str:
    """The generator path AS INVOKED (cwd-relative, like --root) for provenance lines."""
    return Path(sys.argv[0]).as_posix() if sys.argv and sys.argv[0] else "scripts/gen_makefile.py"


def _artifacts(root: Path, out_override: str | None, use_workspace: bool) -> list[tuple[Path, str]]:
    """Deterministic (path, content) list: root Makefile first, then one per member."""
    workspace = None
    if use_workspace:
        workspace = detect_workspace(root)
        logger.debug("workspace members: %s (skipped: %s)", workspace.members, workspace.skipped)
        for name in workspace.skipped:
            logger.warning("skipping member %r: name is not Make/pip-safe", name)
        if not workspace.is_workspace:
            print(f"[warn] --workspace: no member packages found under {root.as_posix()}", file=sys.stderr)
    facts = detect(root)
    logger.debug("detected facts for %s: %s", root.as_posix(), facts)
    root_out = Path(out_override) if out_override else root / "Makefile"
    member_facts = {m: detect(root / m) for m in (workspace.members if workspace else ())}
    for member, mf in member_facts.items():
        logger.debug("member %s facts: %s", member, mf)
    # Never fabricate: only members whose OWN Makefile will carry a `check` target get a
    # check-<member> delegation on the root (install/clean fan-out still covers everyone).
    checkable = tuple(m for m, mf in member_facts.items() if supports_check(mf))
    if workspace and len(checkable) != len(member_facts):
        skipped = sorted(set(member_facts) - set(checkable))
        logger.debug("members without a check target (no check fan-out): %s", skipped)
    program = _program()
    root_regen: list[str] = ["--root", root.as_posix()]
    if use_workspace:
        root_regen.append("--workspace")
    if out_override:
        root_regen += ["--out", out_override]
    artifacts = [
        (
            root_out,
            render_makefile(
                facts,
                workspace=workspace,
                checkable_members=checkable,
                regen_args=tuple(root_regen),
                regen_program=program,
            ),
        )
    ]
    for member, mf in member_facts.items():
        member_regen = ("--root", (root / member).as_posix())
        artifacts.append(
            (root / member / "Makefile", render_makefile(mf, regen_args=member_regen, regen_program=program))
        )
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic Makefile for a Python project.")
    parser.add_argument("--root", default=".", help="Project root to inspect (default: current directory).")
    parser.add_argument("--out", default=None, help="Root Makefile output path (default: <root>/Makefile).")
    parser.add_argument(
        "--workspace",
        action="store_true",
        help="Monorepo mode: fan-out targets on the root Makefile plus one Makefile per member package.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print the root Makefile instead of writing it.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Advisory: exit 1 if any committed artifact differs from a fresh render.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging (prints detected facts).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    root = Path(args.root)
    artifacts = _artifacts(root, args.out, args.workspace)

    if args.stdout:
        sys.stdout.write(artifacts[0][1])  # root Makefile only; members need real paths
        return 0

    if args.check:
        results = [_check_one(path, content) for path, content in artifacts]
        verdict = 1 if any(results) else 0
        logger.debug("--check verdict across %d artifact(s): %s", len(results), "stale" if verdict else "fresh")
        return verdict

    for path, content in artifacts:
        # Guard against the silent-downgrade footgun: regenerating WITHOUT --workspace over
        # a Makefile that has fan-out targets would delete check-all/check-<member>.
        if path.is_file() and "check-all:" in path.read_text(encoding="utf-8") and "check-all:" not in content:
            print(
                f"[warn] {path.as_posix()} previously had workspace fan-out targets; this render drops them"
                " (re-run with --workspace to keep check-all/check-<member>)",
                file=sys.stderr,
            )
        _write_one(path, content)
        print(f"wrote {path.as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
