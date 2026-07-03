"""Tests for emitting a dependencies: block from actual edges."""

from __future__ import annotations

import yaml
from adguard.emit import dependencies_mapping, emit_dependencies_block


def test_mapping_groups_and_sorts():
    edges = {("api", "core"), ("api", "util"), ("engine", "core")}
    assert dependencies_mapping(edges) == {"api": ["core", "util"], "engine": ["core"]}


def test_emit_round_trips_to_same_edges():
    edges = {("api", "core"), ("engine", "core"), ("engine", "plugins")}
    block = emit_dependencies_block(edges)
    parsed = yaml.safe_load(block)["dependencies"]
    rebuilt = {(src, dst) for src, dsts in parsed.items() for dst in dsts}
    assert rebuilt == edges


def test_emit_is_deterministic():
    edges = {("b", "a"), ("a", "c"), ("a", "b")}
    assert emit_dependencies_block(edges) == emit_dependencies_block(set(edges))


def test_emit_empty():
    assert yaml.safe_load(emit_dependencies_block(set()))["dependencies"] == {}
