"""Tests for the grimp-backed extractor against synthetic fixture packages."""

from __future__ import annotations

import os
import sys

import pytest
from adguard.errors import ExtractionError
from adguard.extractor import extract_graph

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture
def on_path():
    """Add fixture package roots to sys.path for the duration of a test."""
    added = []
    for sub in ("clean_pkg", "drift_pkg", "shared_prefix_pkg", "ns_pkg"):
        root = os.path.join(FIXTURES, sub)
        if root not in sys.path:
            sys.path.insert(0, root)
            added.append(root)
    yield
    for root in added:
        sys.path.remove(root)


def test_extracts_direct_edges_only(on_path):
    graph = extract_graph(["clnpkg"])
    assert "clnpkg.api" in graph
    # api directly imports core; the reverse must NOT appear (no transitivity here).
    assert "clnpkg.core" in graph["clnpkg.api"]
    assert "clnpkg.api" not in graph.get("clnpkg.core", set())


def test_back_edge_present_in_drift_fixture(on_path):
    graph = extract_graph(["drfpkg"])
    assert "drfpkg.api" in graph["drfpkg.core"]
    assert "drfpkg.core" in graph["drfpkg.api"]


def test_namespace_package_is_handled(on_path):
    graph = extract_graph(["nspkg"])
    assert "nspkg.mod" in graph


def test_missing_package_raises_extraction_error():
    with pytest.raises(ExtractionError, match="could not build import graph"):
        extract_graph(["definitely_not_a_real_package_xyz"])
