"""Render the actual component graph as a manifest ``dependencies:`` block.

Used by ``drift_check.py --emit-actual`` to bootstrap a manifest from reality.
Output is deterministic (everything sorted) and round-trips: parsing it back
yields the same edge set. A human reviews it before pasting into the manifest —
existing undocumented edges are exactly the drift to surface, not to launder.
"""

from __future__ import annotations

import yaml

from .manifest import Edge


def dependencies_mapping(edges: set[Edge]) -> dict[str, list[str]]:
    """Group edges into a sorted ``{from: [to, ...]}`` mapping."""
    mapping: dict[str, list[str]] = {}
    for src, dst in sorted(edges):
        mapping.setdefault(src, [])
        if dst not in mapping[src]:
            mapping[src].append(dst)
    for src in mapping:
        mapping[src].sort()
    return mapping


def emit_dependencies_block(edges: set[Edge]) -> str:
    """Render a deterministic YAML ``dependencies:`` block."""
    mapping = dependencies_mapping(edges)
    # Typed local so the return type holds with or without yaml stubs installed
    # (the skill CI env is isolated and does not ship types-PyYAML).
    rendered: str = yaml.safe_dump(
        {"dependencies": mapping},
        sort_keys=True,
        default_flow_style=False,
    )
    return rendered
