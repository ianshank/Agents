"""makegen - deterministic Makefile generation for Python projects.

``detect(root)`` inspects a project tree and returns :class:`ProjectFacts`;
``render_makefile(facts)`` turns those facts into byte-stable Makefile text. The split
keeps generation a pure function of observable inputs.
"""

from __future__ import annotations

from .detect import detect
from .model import ProjectFacts
from .render import render_makefile

__all__ = ["ProjectFacts", "detect", "render_makefile"]
