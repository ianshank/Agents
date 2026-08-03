"""Shared utilities for generator scripts across skills.

Consolidates common patterns used by gen_gate.py, gen_deploy.py, and similar
generator scripts to reduce duplication.
"""

from __future__ import annotations

import argparse
import stat
from pathlib import Path
from typing import Any


def make_executable(path: str | Path) -> None:
    """Make a file executable (chmod +x for user, group, other).

    The mode is not considered file content for purposes of change detection,
    so this is safe to call repeatedly without triggering drift detection.

    Args:
        path: Path to the file to make executable
    """
    path = Path(path)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def add_root_argument(parser: argparse.ArgumentParser) -> None:
    """Add a standard --root argument to an argument parser.

    This is used consistently across generator scripts to specify the project root
    directory for which scripts are being generated.

    Args:
        parser: ArgumentParser instance to add the argument to
    """
    parser.add_argument(
        "--root",
        default=".",
        help="Project root (default output is <root>/scripts/...)",
    )


def check_file_freshness(
    out: Path,
    content: str,
    marker: str | None = None,
    marker_split_fn: Any = None,
) -> int:
    """Advisory freshness check for generated files.

    Compares the committed file against fresh content to detect drift.
    Optionally preserves hand-edited sections below a marker (for safety-railed scripts).

    Args:
        out: Path to the generated file
        content: Fresh content to compare against
        marker: Optional marker string that delineates generated vs hand-edited sections
        marker_split_fn: Optional function to split content at marker; signature is
                        (content: str) -> tuple[generated_prefix: str, hand_tail: str]

    Returns:
        0 if file is up to date, 1 if drift detected or file missing
    """
    if not out.is_file():
        print(f"[drift] {out.as_posix()} is missing")
        return 1

    existing_content = out.read_text(encoding="utf-8")

    if marker is None or marker_split_fn is None:
        # Simple full-content comparison
        if existing_content == content:
            print(f"{out.as_posix()} is up to date")
            return 0
        else:
            print(f"[drift] {out.as_posix()} is stale; regenerate")
            return 1

    # Marker-based comparison: only compare generated prefix, ignore hand tail
    fresh_prefix, _ = marker_split_fn(content)
    existing_prefix, existing_tail = marker_split_fn(existing_content)

    if existing_prefix != fresh_prefix:
        print(f"[drift] {out.as_posix()} is stale; regenerate")
        return 1

    if marker_split_fn.__name__ == "split_at_marker" and 'main "$@"' not in existing_tail:
        print(f'[drift] {out.as_posix()}: the main "$@" dispatch line is missing')
        return 1

    print(f"{out.as_posix()} is up to date")
    return 0


__all__ = [
    "add_root_argument",
    "check_file_freshness",
    "make_executable",
]
