"""gategen - deterministic quality-gate shell script generation for Python projects.

``detect(root)`` inspects a project and returns :class:`GateFacts`; ``render_gate(facts)``
turns those facts into a byte-stable, ShellCheck-clean ``quality-gate.sh``.
"""

from __future__ import annotations

from .detect import detect
from .model import GateFacts
from .render import render_ci_snippet, render_gate

__all__ = ["GateFacts", "detect", "render_ci_snippet", "render_gate"]
