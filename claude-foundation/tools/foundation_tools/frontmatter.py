"""YAML frontmatter extraction shared by the validator and the scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_MARKER = "---"


class FrontmatterError(ValueError):
    """Raised when a markdown file's frontmatter block is missing or malformed."""


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(frontmatter, body)`` for markdown ``text``.

    The frontmatter is the YAML mapping between the leading ``---`` markers.
    Raises :class:`FrontmatterError` when the block is absent, unterminated,
    or not a mapping.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _MARKER:
        raise FrontmatterError("missing leading '---' frontmatter marker")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == _MARKER)
    except StopIteration:
        raise FrontmatterError("unterminated frontmatter block") from None
    raw = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")
    return data, "\n".join(lines[end + 1 :])


def load_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Read ``path`` and return its ``(frontmatter, body)``."""
    return split_frontmatter(path.read_text(encoding="utf-8"))
