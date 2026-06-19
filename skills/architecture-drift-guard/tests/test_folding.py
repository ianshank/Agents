"""Tests for folding a module graph into component edges (pure logic)."""
from __future__ import annotations

from adguard.folding import _prefix_index, fold_to_components, module_to_component


def test_longest_prefix_wins():
    components = {"core": ["pkg.core"], "types": ["pkg.core.types"]}
    index = _prefix_index(components)
    assert module_to_component("pkg.core.types", index) == "types"
    assert module_to_component("pkg.core.engine", index) == "core"
    assert module_to_component("pkg.core", index) == "core"


def test_unmapped_module_returns_none():
    index = _prefix_index({"core": ["pkg.core"]})
    assert module_to_component("other.thing", index) is None


def test_fold_drops_intra_and_unmapped_edges():
    components = {"api": ["pkg.api"], "core": ["pkg.core"]}
    graph = {
        "pkg.api": {"pkg.core", "pkg.api.helpers", "os"},  # cross, intra, unmapped
        "pkg.core": set(),
    }
    edges = fold_to_components(graph, components)
    assert edges == {("api", "core")}


def test_fold_back_edge_detected():
    components = {"api": ["pkg.api"], "core": ["pkg.core"]}
    graph = {"pkg.api": {"pkg.core"}, "pkg.core": {"pkg.api"}}
    edges = fold_to_components(graph, components)
    assert edges == {("api", "core"), ("core", "api")}


def test_fold_empty_graph():
    assert fold_to_components({}, {"a": ["pkg.a"]}) == set()


def test_prefix_index_is_sorted_longest_first():
    pairs = _prefix_index({"a": ["x"], "b": ["x.y.z"], "c": ["x.y"]})
    lengths = [len(p[0]) for p in pairs]
    assert lengths == sorted(lengths, reverse=True)
