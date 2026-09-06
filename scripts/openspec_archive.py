#!/usr/bin/env python3
"""Archive an OpenSpec change: ``git mv`` plus outbound relative-link rewrite.

Moving ``openspec/changes/<id>/`` to ``openspec/changes/archive/<id>/`` adds one
path segment. Intra-tree links stay valid; links that point *outside* the moved
directory must be recomputed (blindly prefixing ``../`` is one segment short for
nested ``specs/`` files — the bug this script exists to prevent).

Usage::

    python scripts/openspec_archive.py --change prove-m8-execution --landed 7800a3fe
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(_HERE))

from _cli import configure_logging  # noqa: E402

logger = logging.getLogger(__name__)

_LINK = re.compile(r"\]\(([^)]+)\)")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

GitMv = Callable[[Path, Path, Path], None]


@dataclass(frozen=True)
class OpenSpecArchiveConfig:
    """Layout tunables. Call sites never restate these path segments."""

    changes_dir: str = "openspec/changes"
    archive_dir_name: str = "archive"
    md_suffix: str = ".md"


@dataclass(frozen=True)
class ArchiveResult:
    change_id: str
    source: str
    destination: str
    rewritten: tuple[str, ...]


class ArchiveError(ValueError):
    """The change cannot be archived as requested."""


def _git_mv(repo: Path, src: Path, dst: Path) -> None:
    proc = subprocess.run(
        ["git", "mv", src.as_posix(), dst.as_posix()],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise ArchiveError(f"git mv failed: {err or proc.returncode}")


def _split_target(raw: str) -> tuple[str, str]:
    """Return ``(url, trailing_title)`` from a markdown link destination."""
    text = raw.strip()
    if text.startswith("<") and ">" in text:
        inner, _, rest = text[1:].partition(">")
        return inner.strip(), rest
    url, _, rest = text.partition(" ")
    return url, (f" {rest}" if rest else "")


def should_rewrite(url: str) -> bool:
    if not url or url.startswith("#"):
        return False
    if url.startswith("//") or _SCHEME.match(url):
        return False
    if url.startswith("/"):
        return False
    return True


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def rewrite_outbound_links(
    text: str,
    *,
    old_file: Path,
    new_file: Path,
    moved_root: Path,
) -> str:
    """Recompute relative links that point outside ``moved_root``."""

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        url, title = _split_target(raw)
        if not should_rewrite(url):
            return match.group(0)
        resolved = (old_file.parent / url).resolve()
        if _is_within(resolved, moved_root):
            return match.group(0)
        new_url = Path(os.path.relpath(resolved, new_file.parent)).as_posix()
        return f"]({new_url}{title})"

    return _LINK.sub(repl, text)


def stamp_status(text: str, landed: str) -> str:
    """Replace the ``**Status:**`` token with the archived form, keeping the rest."""
    token = f"implemented (archived; landed `{landed}`)"
    pattern = re.compile(r"(\*\*Status:\*\*\s*)([^·\n]+)")
    if not pattern.search(text):
        return text
    return pattern.sub(lambda m: m.group(1) + token + " ", text, count=1)


def archive_change(
    repo: Path,
    change_id: str,
    cfg: OpenSpecArchiveConfig | None = None,
    *,
    landed: str | None = None,
    git_mv: GitMv | None = None,
) -> ArchiveResult:
    """``git mv`` the change directory and rewrite outbound markdown links."""
    conf = cfg or OpenSpecArchiveConfig()
    if not change_id or "/" in change_id or change_id in (".", ".."):
        raise ArchiveError(f"invalid change id: {change_id!r}")
    changes = repo / conf.changes_dir
    src = changes / change_id
    dst = changes / conf.archive_dir_name / change_id
    if not src.is_dir():
        raise ArchiveError(f"change not found: {src.as_posix()}")
    if dst.exists():
        raise ArchiveError(f"archive destination already exists: {dst.as_posix()}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    md_files = sorted(p for p in src.rglob(f"*{conf.md_suffix}") if p.is_file())
    planned: list[tuple[Path, Path, str]] = []
    for old in md_files:
        rel = old.relative_to(src)
        new = dst / rel
        rewritten = rewrite_outbound_links(
            old.read_text(encoding="utf-8"),
            old_file=old,
            new_file=new,
            moved_root=src,
        )
        if landed and rel.as_posix() == "proposal.md":
            rewritten = stamp_status(rewritten, landed)
        planned.append((old, new, rewritten))
    mover = git_mv or _git_mv
    mover(repo, src, dst)
    rewritten_paths: list[str] = []
    for _old, new, body in planned:
        previous = new.read_text(encoding="utf-8")
        if body != previous:
            new.write_text(body, encoding="utf-8")
            rewritten_paths.append(new.relative_to(repo).as_posix())
    logger.info(
        "archived %s -> %s rewritten=%d",
        src.relative_to(repo).as_posix(),
        dst.relative_to(repo).as_posix(),
        len(rewritten_paths),
    )
    return ArchiveResult(
        change_id=change_id,
        source=src.relative_to(repo).as_posix(),
        destination=dst.relative_to(repo).as_posix(),
        rewritten=tuple(rewritten_paths),
    )


def main(argv: list[str] | None = None) -> int:
    conf = OpenSpecArchiveConfig()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--change", required=True, help="in-flight change directory name")
    ap.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    ap.add_argument("--changes-dir", default=conf.changes_dir)
    ap.add_argument("--archive-dir-name", default=conf.archive_dir_name)
    ap.add_argument("--landed", help="short or full SHA stamped into proposal.md Status")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    configure_logging(verbose=args.verbose)
    cfg = OpenSpecArchiveConfig(
        changes_dir=args.changes_dir,
        archive_dir_name=args.archive_dir_name,
    )
    try:
        result = archive_change(
            Path(args.repo_root).resolve(),
            args.change,
            cfg,
            landed=args.landed,
        )
    except (OSError, ArchiveError) as exc:
        logger.error("%s", exc)
        print(f"openspec-archive FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"archived {result.source} -> {result.destination}")
    for path in result.rewritten:
        print(f"rewrote {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
