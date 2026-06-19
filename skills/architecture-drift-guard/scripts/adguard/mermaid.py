"""Render a manifest into a deterministic Mermaid C4 **Component** diagram.

This enforces the C4 Component level only — one ``Component(...)`` per component
and one ``Rel(...)`` per declared edge. Determinism is critical: the freshness
gate compares a freshly rendered diagram byte-for-byte against the committed
copy, so output must be stable across Python versions and runs. Everything is
sorted, there are no timestamps, and whitespace/newlines are normalised.
"""

from __future__ import annotations

import re

from .manifest import Manifest

DEFAULT_TITLE = "Architecture — Component View"


def normalize_text(text: str) -> str:
    """Canonicalise text for stable comparison: strip trailing whitespace per
    line and end with exactly one trailing newline."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # Drop trailing blank lines, then re-add a single terminator.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _alias(name: str) -> str:
    """Turn a component name into a Mermaid-safe alias (stable, deterministic)."""
    alias = re.sub(r"\W", "_", name)
    if alias and alias[0].isdigit():
        alias = f"c_{alias}"
    return alias or "c"


def render_mermaid(manifest: Manifest) -> str:
    """Render the manifest's components and declared edges as Mermaid C4."""
    title = str(manifest.output.get("title", DEFAULT_TITLE))
    lines: list[str] = ["C4Component", f"    title {title}", ""]

    for name in sorted(manifest.components):
        lines.append(f'    Component({_alias(name)}, "{name}", "Component")')

    edges = sorted(manifest.dependencies)
    if edges:
        lines.append("")
        for src, dst in edges:
            lines.append(f'    Rel({_alias(src)}, {_alias(dst)}, "")')

    return normalize_text("\n".join(lines))
