#!/usr/bin/env python3
"""Tests for scripts/record_audit_verdict.py — idempotent HUMAN_AUDIT wrapper (F-034)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import record_audit_verdict as rav
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

SHA = "a" * 40
SHORT_SHA = "abc1234"


def _seed(store_path: Path, change_id: str = SHA) -> OutcomeStore:
    store = OutcomeStore(store_path)
    store.append(
        OutcomeRecord(
            change_id=change_id,
            domain="human/agent-core",
            raw_confidence=0.0,
            merged_at="2026-01-01T00:00:00+00:00",
        )
    )
    return store


def test_records_correct_and_incorrect_verdicts(tmp_path):
    path = tmp_path / "s.jsonl"
    store = _seed(path)
    assert rav.main(["--store", str(path), "--change-id", SHA, "--correct"]) == rav.EXIT_OK
    resolved = store.resolved()[SHA]
    assert resolved.label is True
    assert resolved.label_source == LabelSource.HUMAN_AUDIT.value

    path2 = tmp_path / "s2.jsonl"
    store2 = _seed(path2, change_id=SHORT_SHA)
    rc = rav.main(["--store", str(path2), "--change-id", SHORT_SHA, "--incorrect"])
    assert rc == rav.EXIT_OK
    assert store2.resolved()[SHORT_SHA].label is False


def test_redispatch_on_audited_record_is_logged_noop(tmp_path, caplog):
    path = tmp_path / "s.jsonl"
    store = _seed(path)
    assert rav.main(["--store", str(path), "--change-id", SHA, "--correct"]) == rav.EXIT_OK
    lines_before = len(store.all())
    with caplog.at_level(logging.INFO):
        rc = rav.main(["--store", str(path), "--change-id", SHA, "--incorrect"])
    assert rc == rav.EXIT_OK
    assert len(store.all()) == lines_before  # nothing appended
    assert store.resolved()[SHA].label is True  # original verdict stands
    assert any("no-op" in r.message for r in caplog.records)


def test_unknown_change_id_fails_loudly(tmp_path):
    path = tmp_path / "s.jsonl"
    _seed(path)
    rc = rav.main(["--store", str(path), "--change-id", "b" * 40, "--correct"])
    assert rc == rav.EXIT_UNKNOWN_CHANGE


@pytest.mark.parametrize("bad", ["not-a-sha", "abc", "A" * 40, "$(rm -rf /)", ""])
def test_malformed_change_id_rejected(tmp_path, bad):
    path = tmp_path / "s.jsonl"
    _seed(path)
    assert rav.record(str(path), bad, correct=True, actor="t") == rav.EXIT_CONFIG


def test_actor_resolution(monkeypatch):
    assert rav.resolve_actor("cli-actor") == "cli-actor"
    monkeypatch.setenv(rav.DEFAULT_ACTOR_ENV, "env-actor")
    assert rav.resolve_actor(None) == "env-actor"
    monkeypatch.delenv(rav.DEFAULT_ACTOR_ENV)
    assert rav.resolve_actor(None) == "unknown"


def test_internal_error_exits_1(tmp_path, capsys):
    rc = rav.main(["--store", str(tmp_path), "--change-id", SHA, "--correct"])
    assert rc == rav.EXIT_INTERNAL
    assert "internal error" in capsys.readouterr().err


def test_verdict_flag_required(tmp_path):
    with pytest.raises(SystemExit) as exc:
        rav.main(["--store", "s.jsonl", "--change-id", SHA])
    assert exc.value.code == 2
