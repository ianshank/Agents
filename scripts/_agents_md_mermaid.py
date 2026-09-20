#!/usr/bin/env python3
"""Mermaid structural checks for AGENTS.md files.

Kept separate from ``_agents_md_lib`` so both stay inside the ADR 0019 500-line budget.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _agents_md_lib import Doc, Finding

MERMAID_DIAGRAM_TYPES: tuple[str, ...] = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "journey",
    "gantt",
    "C4Component",
    "C4Context",
    "C4Container",
    "mindmap",
    "timeline",
)
MERMAID_MIN_NODES = 5
MERMAID_MAX_NODES = 15

_MERMAID_OPEN_RE = re.compile(r"^\s*```mermaid\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_SUBGRAPH_RE = re.compile(r"^\s*subgraph\s+([A-Za-z_][\w]*)")
_NODE_DEF_RE = re.compile(r"(?:^|[\s;])([A-Za-z_][\w]*)\s*(?:\[|\(|\{)")
_EDGE_LEFT_RE = re.compile(r"(?:^|[\s;])([A-Za-z_][\w]*)\s*(?:-->|---|-\.->|==>)")
_EDGE_RIGHT_RE = re.compile(r"(?:-->|---|-\.->|==>)\s*([A-Za-z_][\w]*)")
_MERMAID_SKIP = frozenset(
    {
        "flowchart",
        "graph",
        "LR",
        "RL",
        "TD",
        "TB",
        "BT",
        "subgraph",
        "end",
        "style",
        "linkStyle",
        "click",
        "direction",
    }
)


def _mermaid_blocks(doc: Doc) -> tuple[list[list[str]], list[Finding]]:
    """Split out every mermaid fence. An unterminated fence is itself a finding."""
    from _agents_md_lib import Finding

    blocks: list[list[str]] = []
    findings: list[Finding] = []
    current: list[str] | None = None
    for line in doc.lines:
        if current is None:
            if _MERMAID_OPEN_RE.match(line):
                current = []
            continue
        if _FENCE_CLOSE_RE.match(line):
            blocks.append(current)
            current = None
            continue
        if line.lstrip().startswith("```"):
            findings.append(
                Finding(
                    doc.rel,
                    "mermaid",
                    f"unterminated ```mermaid fence before {line.strip()!r}",
                )
            )
            current = None
            continue
        current.append(line)
    if current is not None:
        findings.append(Finding(doc.rel, "mermaid", "unterminated ```mermaid fence"))
    return blocks, findings


def _mermaid_nodes(block: list[str]) -> set[str]:
    """Unique node / subgraph ids in a mermaid body (definitions and edge endpoints)."""
    nodes: set[str] = set()
    for line in block:
        stripped = line.strip()
        if not stripped or stripped.startswith(("accTitle", "accDescr", "classDef", "class ")):
            continue
        match = _SUBGRAPH_RE.match(line)
        if match:
            nodes.add(match.group(1))
        for regex in (_NODE_DEF_RE, _EDGE_LEFT_RE, _EDGE_RIGHT_RE):
            for hit in regex.finditer(line):
                tok = hit.group(1)
                if tok not in _MERMAID_SKIP:
                    nodes.add(tok)
    return nodes


def check_mermaid(doc: Doc) -> list[Finding]:
    """Exactly one diagram per file, with a11y metadata, 5-15 nodes, and ``classDef here``."""
    from _agents_md_lib import Finding

    blocks, findings = _mermaid_blocks(doc)
    if len(blocks) != 1:
        if not blocks:
            findings.append(
                Finding(
                    doc.rel,
                    "mermaid",
                    "no ```mermaid diagram; every AGENTS.md carries one",
                )
            )
        else:
            findings.append(
                Finding(
                    doc.rel,
                    "mermaid",
                    f"expected exactly 1 ```mermaid diagram, found {len(blocks)}",
                )
            )
        return findings

    block = blocks[0]
    label = "diagram 1"
    body = [ln for ln in block if ln.strip()]
    if not body:
        findings.append(Finding(doc.rel, "mermaid", f"{label} is empty"))
        return findings

    header = body[0].strip()
    if not any(header.startswith(kind) for kind in MERMAID_DIAGRAM_TYPES):
        findings.append(Finding(doc.rel, "mermaid", f"{label} has an unrecognised type: {header!r}"))
    joined = "\n".join(block)
    findings.extend(
        Finding(doc.rel, "mermaid", f"{label} is missing {keyword} - screen readers need it")
        for keyword in ("accTitle:", "accDescr:")
        if keyword not in joined
    )
    if "classDef here" not in joined:
        findings.append(
            Finding(
                doc.rel,
                "mermaid",
                f"{label} is missing classDef here - highlight the current directory",
            )
        )
    node_count = len(_mermaid_nodes(block))
    if not MERMAID_MIN_NODES <= node_count <= MERMAID_MAX_NODES:
        findings.append(
            Finding(
                doc.rel,
                "mermaid",
                f"{label} has {node_count} nodes; expected {MERMAID_MIN_NODES}-{MERMAID_MAX_NODES}",
            )
        )
    for line in block:
        if not line.isascii():
            findings.append(
                Finding(
                    doc.rel,
                    "mermaid",
                    f"{label} has non-ASCII text ({line.strip()!r}); "
                    "GitHub's renderer breaks on emoji and extended characters",
                )
            )
            break
    return findings
