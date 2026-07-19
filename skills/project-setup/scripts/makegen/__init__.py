"""makegen - deterministic Makefile generation for Python projects.

``detect(root)`` inspects a project tree and returns :class:`ProjectFacts`;
``render_makefile(facts)`` turns those facts into byte-stable Makefile text;
``detect_workspace(root)`` finds monorepo members (immediate-child ``pyproject.toml``
directories) for the optional workspace fan-out. The split keeps generation a pure
function of observable inputs.
"""

from __future__ import annotations

from .detect import detect
from .model import ProjectFacts
from .render import render_makefile
from .workspace import WorkspaceFacts, detect_workspace

__all__ = ["ProjectFacts", "WorkspaceFacts", "detect", "detect_workspace", "render_makefile"]
