"""gategen - deterministic quality-gate shell script generation for Python projects.

``detect(root)`` inspects a project and returns :class:`GateFacts`; ``render_gate(facts)``
turns those facts into a byte-stable, ShellCheck-clean ``quality-gate.sh``. ``MARKER`` /
``split_at_marker`` expose the hand-extension seam (generator-owned prefix vs preserved tail).
"""

from __future__ import annotations

from .detect import detect
from .model import GateFacts
from .render import MARKER, render_ci_snippet, render_gate, split_at_marker

__all__ = ["MARKER", "GateFacts", "detect", "render_ci_snippet", "render_gate", "split_at_marker"]
