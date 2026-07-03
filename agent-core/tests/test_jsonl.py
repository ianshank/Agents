"""Tests for the shared strict JSONL reader (agent_core.jsonl)."""

from __future__ import annotations

import json

import pytest

from agent_core.jsonl import iter_jsonl, read_jsonl
from agent_core.outcome_store import OutcomeRecord, OutcomeStore


def test_read_jsonl_missing_file_is_empty(tmp_path):
    assert read_jsonl(tmp_path / "absent.jsonl", json.loads) == []


def test_read_jsonl_skips_blank_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a": 1}\n\n   \n{"a": 2}\n', encoding="utf-8")
    assert read_jsonl(p, json.loads) == [{"a": 1}, {"a": 2}]


def test_iter_jsonl_streams_lazily(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    it = iter_jsonl(p, json.loads)
    assert next(it) == {"a": 1}
    assert next(it) == {"a": 2}
    with pytest.raises(StopIteration):
        next(it)


def test_read_jsonl_strict_on_malformed_line(tmp_path):
    # Strict by design: a corrupt line in an append-only audit store must raise,
    # not be silently skipped.
    p = tmp_path / "s.jsonl"
    p.write_text('{"a": 1}\nnot json\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        read_jsonl(p, json.loads)


def test_read_jsonl_applies_factory(tmp_path):
    rec = OutcomeRecord(
        change_id="c1", domain="core", raw_confidence=0.5, merged_at="2000-01-01T00:00:00+00:00"
    )
    p = tmp_path / "s.jsonl"
    p.write_text(rec.to_json() + "\n", encoding="utf-8")
    assert read_jsonl(p, OutcomeRecord.from_json) == [rec]


def test_outcome_store_round_trips_through_shared_reader(tmp_path):
    # OutcomeStore.all() delegates to read_jsonl: behavior is unchanged.
    store = OutcomeStore(tmp_path / "s.jsonl")
    assert store.all() == []
    rec = OutcomeRecord(
        change_id="c1", domain="core", raw_confidence=0.5, merged_at="2000-01-01T00:00:00+00:00"
    )
    store.append(rec)
    assert store.all() == [rec]


def test_read_jsonl_logs_record_count(tmp_path, caplog):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    with caplog.at_level("DEBUG", logger="agent_core.jsonl"):
        read_jsonl(p, json.loads)
    assert any("read 1 records" in r.message for r in caplog.records)


def test_iter_jsonl_missing_file_logs_debug(tmp_path, caplog):
    with caplog.at_level("DEBUG", logger="agent_core.jsonl"):
        assert list(iter_jsonl(tmp_path / "absent.jsonl", json.loads)) == []
    assert any("does not exist" in r.message for r in caplog.records)
