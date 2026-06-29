"""Targeted tests for previously-uncovered normalize/ingest branches (coverage margin)."""

from __future__ import annotations

from forge import ingest, normalize


def test_explicit_action_types_are_honoured() -> None:
    # An explicit, valid expected_action_types list is carried through verbatim.
    obj = {"prompt": "do it", "expected_action_types": ["retrieve", "call_tool"]}
    canonical = normalize.to_canonical(("f.jsonl", "1", obj))
    assert canonical["metadata"]["expected_action_types"] == ["retrieve", "call_tool"]


def test_explicit_action_types_ignored_when_all_invalid() -> None:
    # All-unknown explicit types fall back to evidence-based inference; with no evidence
    # the canonical schema records "unclassified" rather than fabricating an action.
    obj = {"prompt": "do it", "expected_action_types": ["bogus"]}
    canonical = normalize.to_canonical(("f.jsonl", "1", obj))
    assert canonical["metadata"]["expected_action_types"] == ["unclassified"]


def test_coerce_cell_recovers_from_invalid_json() -> None:
    # A cell that looks structured but is not valid JSON degrades to the raw string.
    assert ingest._coerce_cell("{not json") == "{not json"


def test_coerce_cell_parses_scalar_json() -> None:
    assert ingest._coerce_cell("true") is True
    assert ingest._coerce_cell("") is None
