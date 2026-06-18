"""Packaging-contract tests: metadata that must not silently drift.

These guard the A1-A3 hardening: the dev extra exists, the PEP 561 marker ships,
and the package version is single-sourced from ``agent_core.version.__version__``
(kept distinct from the config ``SCHEMA_VERSION``).
"""
from __future__ import annotations

import importlib.metadata as md
import pathlib

import pytest

import agent_core
from agent_core import version as _version

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    tomllib = pytest.importorskip("tomllib")  # stdlib on 3.11+; skip on 3.10 source runs
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))


def test_dev_extra_declares_toolchain() -> None:
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    names = {d.split(">")[0].split("=")[0].split("[")[0].strip().lower() for d in dev}
    assert {"pytest", "pytest-cov", "hypothesis", "ruff", "mypy"} <= names


def test_py_typed_marker_present() -> None:
    assert (ROOT / "agent_core" / "py.typed").is_file(), "PEP 561 marker missing"


def test_version_is_single_source_of_truth() -> None:
    try:
        dist = md.version("agent-core")
    except md.PackageNotFoundError:  # pragma: no cover - only on a bare, uninstalled checkout
        pytest.skip("agent-core not installed; run `pip install -e .`")
    assert agent_core.__version__ == dist


def test_schema_version_is_independent_constant() -> None:
    # __version__ (package) and SCHEMA_VERSION (config schema) are distinct names that
    # may diverge later; both must stay exported.
    assert isinstance(_version.SCHEMA_VERSION, str)
    assert isinstance(_version.__version__, str)
    assert "SCHEMA_VERSION" in agent_core.__all__
    assert "__version__" in agent_core.__all__
