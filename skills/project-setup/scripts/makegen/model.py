"""Deterministic facts about a Python project, derived only from its files.

``ProjectFacts`` is a frozen value object: detection (``detect.py``) produces it from
the project tree, and rendering (``render.py``) turns it into Makefile text. Keeping the
two sides separated by a plain data class is what makes the generator a pure, testable
function of observable inputs — no hidden state, no runtime inference.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectFacts:
    """Everything the Makefile renderer needs, all derived deterministically."""

    python: str = "python3"
    package_manager: str = "pip"  # pip | poetry | pdm | uv | hatch
    install_cmd: str = "$(PIP) install -e ."
    has_ruff: bool = False
    type_checker: str | None = None  # "mypy" | "pyright" | None
    typecheck_paths: str = "."
    has_pytest: bool = False
    has_pytest_cov: bool = False
    coverage_source: str = "."
    cov_fail_under: int = 0
    src_layout: bool = False
    has_build_backend: bool = False
    has_quality_gate_script: bool = False
    has_deploy_script: bool = False
