"""Shared utilities for scripts and validations across the Agents codebase.

Consolidates common patterns to reduce duplication:
- sys.path manipulation for test imports
- JSON loading with consistent error handling
- Logging configuration
- Generator utility functions
- Argument parsing helpers
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any


def add_scripts_to_path(scripts_dir: str | None = None) -> None:
    """Ensure the scripts directory is on sys.path for imports.

    This is used by conftest.py files and scripts that need to import
    from the scripts directory. If scripts_dir is not provided, uses the
    directory containing this file.

    Args:
        scripts_dir: Path to the scripts directory. If None, uses the directory
                    containing this module.
    """
    import sys

    if scripts_dir is None:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))

    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def configure_logging(
    name: str = "scripts",
    level: int = logging.INFO,
    format_string: str | None = None,
) -> logging.Logger:
    """Configure standard logging for scripts and validations.

    Args:
        name: Logger name (typically the script or module name)
        level: Logging level (default: INFO)
        format_string: Custom format string. If None, uses standard format.

    Returns:
        Configured logger instance
    """
    if format_string is None:
        format_string = "%(levelname)s: %(message)s"

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(format_string))

    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(handler)

    return logger


def safe_json_load(
    path: str | Path,
    default: Any = None,
    raise_on_error: bool = False,
) -> Any:
    """Safely load JSON from a file with consistent error handling.

    Args:
        path: Path to the JSON file
        default: Default value to return on error (if raise_on_error is False)
        raise_on_error: If True, raise exceptions; if False, log and return default

    Returns:
        Parsed JSON object, or default if an error occurs

    Raises:
        json.JSONDecodeError: If raise_on_error is True and JSON is invalid
        OSError: If raise_on_error is True and file cannot be read
    """
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        if raise_on_error:
            raise
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to load JSON from {path}: {e}")
        return default


def safe_json_loads(
    text: str,
    default: Any = None,
    raise_on_error: bool = False,
) -> Any:
    """Safely parse JSON from a string with consistent error handling.

    Args:
        text: JSON string to parse
        default: Default value to return on error (if raise_on_error is False)
        raise_on_error: If True, raise exceptions; if False, log and return default

    Returns:
        Parsed JSON object, or default if an error occurs

    Raises:
        json.JSONDecodeError: If raise_on_error is True and JSON is invalid
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        if raise_on_error:
            raise
        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to parse JSON: {e}")
        return default


def check_file_exists(path: str | Path) -> bool:
    """Check if a file exists.

    Args:
        path: Path to check

    Returns:
        True if path is a file, False otherwise
    """
    return os.path.isfile(path)


def make_executable(path: str | Path) -> None:
    """Make a file executable (chmod +x for user, group, other).

    The mode is not considered file content for purposes of change detection,
    so this is safe to call repeatedly.

    Args:
        path: Path to the file to make executable
    """
    path = Path(path)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def is_file_stale(output_path: str | Path, expected_content: str) -> bool:
    """Check if an output file needs regeneration.

    Compares file content with expected content. Used by generators to avoid
    regenerating unchanged files.

    Args:
        output_path: Path to the output file
        expected_content: Expected file content

    Returns:
        True if the file doesn't exist or has different content, False if current
    """
    output_path = Path(output_path)
    if not output_path.exists():
        return True

    try:
        with open(output_path, encoding="utf-8") as f:
            return f.read() != expected_content
    except OSError:
        return True


__all__ = [
    "add_scripts_to_path",
    "configure_logging",
    "safe_json_load",
    "safe_json_loads",
    "check_file_exists",
    "make_executable",
    "is_file_stale",
]
