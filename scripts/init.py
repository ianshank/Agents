#!/usr/bin/env python3
"""Cross-platform project initialisation script (replaces init.sh).

Creates a virtual-environment (if it does not already exist), installs the
project with ``[dev,openai]`` extras, and prints *baseline ready* on success.

Idempotent – safe to run multiple times.

Exit codes:
    0 – success
    1 – a step failed
"""
from __future__ import annotations

import logging
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENV_DIR: str = ".venv"
INSTALL_EXTRAS: str = ".[dev,openai]"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> Path:
    """Return the project root (parent of the ``scripts/`` directory)."""
    return Path(__file__).resolve().parent.parent


def _venv_python(venv_dir: Path) -> Path:
    """Return the path to the venv's Python interpreter, per platform."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_pip(venv_dir: Path) -> Path:
    """Return the path to the venv's pip, per platform."""
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "pip"


def _activate_hint(venv_dir: Path) -> str:
    """Return the shell-appropriate activate command for informational output."""
    if platform.system() == "Windows":
        return str(venv_dir / "Scripts" / "activate.bat")
    return f"source {venv_dir / 'bin' / 'activate'}"


def _create_venv(venv_dir: Path) -> bool:
    """Create the virtual-environment if it does not already exist.

    Returns *True* on success (or if it already existed).
    """
    if venv_dir.exists() and _venv_python(venv_dir).exists():
        logger.info("Virtual-environment already exists at %s", venv_dir)
        return True

    logger.info("Creating virtual-environment at %s …", venv_dir)
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Failed to create venv:\n%s", result.stderr)
        return False
    logger.info("Virtual-environment created ✓")
    return True


def _install_deps(venv_dir: Path, project_root: Path) -> bool:
    """Install the project in editable mode with dev+openai extras.

    Returns *True* on success.
    """
    pip = str(_venv_pip(venv_dir))
    python = str(_venv_python(venv_dir))

    # Prefer using the venv python -m pip for robustness
    cmd = [python, "-m", "pip", "install", "-q", "-e", INSTALL_EXTRAS]
    logger.info("Installing dependencies: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("pip install failed:\n%s", result.stderr)
        return False
    logger.info("Dependencies installed ✓")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run initialisation steps and return an exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    project_root = _project_root()
    venv_dir = project_root / VENV_DIR

    logger.info("Project root: %s", project_root)
    logger.info("Platform:     %s", platform.system())

    if not _create_venv(venv_dir):
        return 1

    if not _install_deps(venv_dir, project_root):
        return 1

    logger.info("Activate with: %s", _activate_hint(venv_dir))
    print("baseline ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
