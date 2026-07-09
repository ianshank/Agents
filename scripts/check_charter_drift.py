#!/usr/bin/env python3
"""CI guard: keep ``docs/CHARTER.md`` from drifting away from the repo it governs.

The charter (§ Status & Purpose) points at authoritative sources — ``AGENTS.md``,
``README.md``, ``NEXT_STEPS.md``, individual ADRs under ``docs/decisions/`` — instead of
restating their content, precisely so those references can be verified mechanically. This
guard extracts every **markdown link target** from the charter and asserts each local
target resolves to an existing repo path (file *or* directory). Both inline links
``[text](target)`` and reference-style link definitions ``[label]: target`` are parsed, so a
dead reference cannot hide behind either syntax. ADR references are ordinary links
(``[ADR 0004](decisions/0004-auto-fix-loop.md)``), so they are covered by the same existence
check — no separate range parsing (charter prose such as "ADRs 0010-0016" is not a filename
and is deliberately never treated as one).

Each captured target is normalized before checking: an optional CommonMark title
(``[a](url "title")``) is dropped, angle-bracketed ``<url>`` forms are unwrapped, and any
trailing ``#anchor`` / ``?query`` is stripped.

What is intentionally NOT a drift signal, to avoid false positives:
  * External links (``http(s)://``, ``mailto:``, protocol-relative ``//``) and pure anchors
    (``#section``).
  * Absolute paths (``/etc/passwd``, or root-relative ``/docs/...``) — this guard only
    verifies paths relative to the charter, so absolutes are skipped rather than resolved
    against the filesystem root.
  * Glob patterns and code identifiers that merely contain a slash — e.g.
    ``scripts/validations/**`` or ``ship/hold/escalate`` — which appear as *inline code*,
    not link targets, and so are never inspected. Any target containing a glob metacharacter
    (``*``, ``?``, ``[``, ``]``) is skipped.

Link targets are resolved relative to the charter file's own directory (standard markdown
semantics), so ``../NEXT_STEPS.md`` and ``decisions/0004-....md`` both resolve correctly.
Paths are emitted with ``.as_posix()`` for deterministic, cross-platform output. (One known
limitation: a target containing literal unescaped parentheses, e.g. ``diagram(1).png``, is
truncated at the first ``)`` — such filenames do not occur in this repo.)

  python scripts/check_charter_drift.py            # check docs/CHARTER.md
  python scripts/check_charter_drift.py --charter path/to/OTHER.md
  python scripts/check_charter_drift.py -v         # DEBUG: list every reference

Exit codes:
    0 - every local link target resolves
    1 - at least one local link target is a dead reference
    2 - configuration / usage error (charter file missing, unreadable, or not UTF-8)
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from _cli import configure_logging

logger = logging.getLogger(__name__)

# Exit code for a configuration / usage error (matches the module docstring contract).
EXIT_USAGE_ERROR = 2

# Charter location relative to the repo root, as a POSIX-style relative path. Single source
# of truth; the default resolves against the repo root at call time (see _default_charter).
DEFAULT_CHARTER_RELPATH = "docs/CHARTER.md"

# Markdown inline link: capture the raw target inside [text](target). The target may still
# carry a CommonMark title or angle brackets; _extract_url normalizes that.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# Reference-style link definition at the start of a line: [label]: target ["title"].
_LINK_DEF_RE = re.compile(r"(?m)^[ \t]*\[[^\]]+\]:[ \t]*(\S.*)$")

# A target with any of these is a pattern/placeholder, not a concrete path to check.
_GLOB_CHARS = ("*", "?", "[", "]")

# Targets we never treat as local repo paths.
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "//", "#")


@dataclass(frozen=True)
class DeadLink:
    """One markdown link whose local target does not resolve to a repo path."""

    target: str  # the raw target as written in the charter
    resolved: str  # absolute path it resolved to (POSIX), for the report


def _repo_root() -> Path:
    """Repo root (parent of the ``scripts/`` directory holding this file)."""
    return Path(__file__).resolve().parent.parent


def _default_charter() -> Path:
    """Absolute path to the charter this guard checks by default."""
    return _repo_root() / DEFAULT_CHARTER_RELPATH


def _extract_url(raw: str) -> str:
    """Reduce a raw link target to just its URL/path portion.

    Handles the two CommonMark forms that otherwise corrupt the path: an angle-bracketed
    ``<path with spaces>`` target (unwrapped, preserving internal spaces) and a trailing
    title ``path "title"`` / ``path 'title'`` / ``path (title)`` (dropped — for a plain
    inline target the URL is the first whitespace-delimited token).
    """
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        return raw[1:end] if end != -1 else raw[1:]
    parts = raw.split(None, 1)
    return parts[0] if parts else ""


def _strip_fragment(target: str) -> str:
    """Drop a trailing ``#anchor`` or ``?query`` so only the path portion remains."""
    for separator in ("#", "?"):
        target = target.split(separator, 1)[0]
    return target


def _normalize_target(raw: str) -> str:
    """Normalize a raw link target to the local path we should check (URL → no title/anchor)."""
    return _strip_fragment(_extract_url(raw))


def _is_checkable_local_link(target: str) -> bool:
    """True when *target* is a local, relative path we should assert exists.

    Excludes empty targets, external/anchor links, absolute paths (not resolvable relative
    to the charter), and glob/pattern targets — those are legitimate charter content, not
    references to a concrete repo file.
    """
    if not target or target.startswith(_EXTERNAL_PREFIXES):
        return False
    # A POSIX-style absolute target ("/docs/...") is not recognized as absolute by
    # Path.is_absolute() on Windows, so check the leading separator explicitly too — this
    # keeps the guard (and its tests) deterministic across platforms.
    if target.startswith(("/", "\\")) or Path(target).is_absolute():
        return False
    return not any(char in target for char in _GLOB_CHARS)


def _iter_raw_targets(text: str) -> list[str]:
    """Every raw target from inline links and reference-style link definitions."""
    raws = [m.group(1) for m in _LINK_RE.finditer(text)]
    raws.extend(m.group(1) for m in _LINK_DEF_RE.finditer(text))
    return raws


def extract_local_targets(text: str) -> list[str]:
    """Every distinct, checkable local link target in *text*, in first-seen order.

    Covers both inline links ``[t](url)`` and reference definitions ``[label]: url``.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in _iter_raw_targets(text):
        # Normalize (URL extraction + #anchor/?query strip) *before* classifying so a query
        # string is not mistaken for a glob and a bare #anchor collapses to "".
        target = _normalize_target(raw)
        if not _is_checkable_local_link(target):
            continue
        if target not in seen:
            seen.add(target)
            ordered.append(target)
    return ordered


def find_dead_links(charter_path: Path) -> list[DeadLink]:
    """Return every local link target in *charter_path* that does not resolve.

    Targets resolve relative to the charter file's own directory, per markdown semantics.
    A target is considered live if it exists as either a file or a directory.
    """
    text = charter_path.read_text(encoding="utf-8")
    base = charter_path.resolve().parent
    dead: list[DeadLink] = []
    for target in extract_local_targets(text):
        resolved = (base / target).resolve()
        exists = resolved.exists()
        logger.debug("reference %s -> %s (%s)", target, resolved.as_posix(), "ok" if exists else "MISSING")
        if not exists:
            dead.append(DeadLink(target, resolved.as_posix()))
    return dead


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Check the project charter for dead references.")
    parser.add_argument(
        "--charter",
        default=None,
        help=f"Path to the charter markdown (default: {DEFAULT_CHARTER_RELPATH} at the repo root).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the charter-drift check and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    charter = Path(args.charter) if args.charter else _default_charter()
    if not charter.is_file():
        logger.error("charter file not found: %s", charter.as_posix())
        print(f"charter-drift: usage error — no such charter file: {charter.as_posix()}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    try:
        dead = find_dead_links(charter)
    except (OSError, UnicodeDecodeError) as exc:
        # An unreadable or non-UTF-8 charter is an operator error, not drift: honour the
        # documented exit-2 contract rather than surfacing a traceback that looks like exit 1.
        logger.error("cannot read charter %s: %s", charter.as_posix(), exc)
        print(f"charter-drift: usage error — cannot read {charter.as_posix()}: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    if dead:
        # Drift is the outcome an operator most wants in structured CI logs — emit a log
        # record (the usage-error and success paths already log), not just stdout.
        logger.warning("charter-drift: %d dead reference(s) in %s", len(dead), charter.as_posix())
        print(f"charter-drift: FAIL - {len(dead)} dead reference(s) in {charter.as_posix()}:")
        for link in dead:
            print(f"  {link.target} -> {link.resolved} (missing)")
        return 1

    logger.info("charter-drift: OK - all references in %s resolve", charter.as_posix())
    print(f"charter-drift: OK - every reference in {charter.name} resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
