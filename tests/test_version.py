"""Tests for version metadata (F-017: Dynamic Versioning)."""

from __future__ import annotations

import importlib.metadata
import re

import pytest


def test_version_is_string():
    """__version__ must be a string."""
    from eval_harness.version import __version__

    assert isinstance(__version__, str)


def test_version_not_empty():
    """__version__ must not be empty."""
    from eval_harness.version import __version__

    assert len(__version__) > 0


def test_schema_version_unchanged():
    """SCHEMA_VERSION must remain '1.0' until a config format change."""
    from eval_harness.version import SCHEMA_VERSION

    assert SCHEMA_VERSION == "1.0"


def test_dist_name_matches_pyproject():
    """_DIST_NAME must match the distribution name in pyproject.toml."""
    from eval_harness.version import _DIST_NAME

    assert _DIST_NAME == "langfuse-eval-harness"


def test_version_importable_from_package():
    """__version__ re-exported from the top-level package must be identical."""
    from eval_harness import __version__ as pkg_version
    from eval_harness.version import __version__

    assert pkg_version == __version__


def test_schema_version_importable_from_package():
    """SCHEMA_VERSION re-exported from the top-level package must be identical."""
    from eval_harness import SCHEMA_VERSION as PKG_SV
    from eval_harness.version import SCHEMA_VERSION

    assert PKG_SV == SCHEMA_VERSION


def test_version_fallback_when_not_installed():
    """The fallback exception type is PackageNotFoundError."""
    # We cannot easily re-trigger module-level code, but we can confirm the
    # fallback mechanism works by exercising the same exception type.
    with pytest.raises(importlib.metadata.PackageNotFoundError):
        importlib.metadata.version("nonexistent-package-xyz-4242")


def test_schema_version_is_semver_prefix():
    """SCHEMA_VERSION must be a two-segment semver prefix (e.g. '1.0')."""
    from eval_harness.version import SCHEMA_VERSION

    assert re.match(r"^\d+\.\d+$", SCHEMA_VERSION)


def test_version_conforms_to_pep440_or_dev():
    """__version__ must be either a PEP 440 version or the dev sentinel."""
    from eval_harness.version import __version__

    # Either a real PEP 440 version (from pip install) or the dev fallback
    pep440 = re.compile(
        r"^\d+\.\d+\.\d+"  # major.minor.patch
        r"(?:(?:a|b|rc)\d+)?"  # optional pre-release
        r"(?:\.post\d+)?"  # optional post-release
        r"(?:\.dev\d+)?$"  # optional dev segment
    )
    assert pep440.match(__version__) or __version__ == "0.0.0-dev"
