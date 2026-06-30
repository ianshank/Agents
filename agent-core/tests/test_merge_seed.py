"""Tests for the merge-time outcome seeder (F-010 audit-data seam)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.audit_sampler import record_verdict
from agent_core.merge_seed import already_seeded, main, seed_pending
from agent_core.outcome_store import LabelSource, OutcomeStore

FIXED = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_seed_pending_writes_pending_record(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    rec = seed_pending(store, "c1", "core", 0.91, now=FIXED)
    assert rec is not None
    assert rec.change_id == "c1"
    assert rec.domain == "core"
    assert rec.raw_confidence == 0.91
    assert rec.label is None  # pending
    assert rec.label_source is None
    assert rec.merged_at == FIXED.isoformat()
    # persisted and round-trips
    [loaded] = store.all()
    assert loaded == rec


def test_seed_pending_is_idempotent(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    first = seed_pending(store, "c1", "core", 0.91, now=FIXED)
    second = seed_pending(store, "c1", "core", 0.91, now=FIXED)
    assert first is not None
    assert second is None  # already seeded -> no-op
    assert len(store.all()) == 1


def test_already_seeded_predicate(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    assert already_seeded(store, "c1") is False
    seed_pending(store, "c1", "core", 0.5, now=FIXED)
    assert already_seeded(store, "c1") is True
    assert already_seeded(store, "other") is False


def test_explicit_merged_at_and_agent_version(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    rec = seed_pending(
        store, "c1", "core", 0.5, merged_at="2026-01-02T03:04:05+00:00", agent_version="abc123"
    )
    assert rec is not None
    assert rec.merged_at == "2026-01-02T03:04:05+00:00"
    assert rec.agent_version == "abc123"


def test_default_merged_at_is_utc_now(tmp_path):
    # No explicit merged_at / now -> falls back to datetime.now(UTC); just assert
    # it produced a parseable aware ISO timestamp.
    store = OutcomeStore(tmp_path / "s.jsonl")
    rec = seed_pending(store, "c1", "core", 0.5)
    assert rec is not None
    parsed = datetime.fromisoformat(rec.merged_at)
    assert parsed.tzinfo is not None


def test_seeded_record_is_resolvable_by_audit_sampler(tmp_path):
    """The seam's purpose: a seeded pending record can be human-audited.

    Before seeding, record_verdict raises KeyError (no record to resolve).
    After seeding, the verdict attaches as an authoritative HUMAN_AUDIT label.
    """
    store = OutcomeStore(tmp_path / "s.jsonl")
    with pytest.raises(KeyError):
        record_verdict(store, "c1", correct=True)

    seed_pending(store, "c1", "core", 0.91, now=FIXED)
    rec = record_verdict(store, "c1", correct=True, now=FIXED)
    assert rec.label is True
    assert rec.label_source == LabelSource.HUMAN_AUDIT.value
    # resolved() now yields the authoritative audit record
    resolved = store.resolved()["c1"]
    assert resolved.label_source == LabelSource.HUMAN_AUDIT.value


def test_cli_seeds_and_reports(tmp_path, capsys):
    store_path = str(tmp_path / "s.jsonl")
    rc = main(
        ["--store", store_path, "--change-id", "c1", "--domain", "core", "--raw-confidence", "0.9"]
    )
    assert rc == 0
    assert "seeded pending outcome c1" in capsys.readouterr().out
    assert len(OutcomeStore(store_path).all()) == 1


def test_cli_idempotent_no_op(tmp_path, capsys):
    store_path = str(tmp_path / "s.jsonl")
    argv = [
        "--store",
        store_path,
        "--change-id",
        "c1",
        "--domain",
        "core",
        "--raw-confidence",
        "0.9",
    ]
    assert main(argv) == 0
    capsys.readouterr()
    assert main(argv) == 0  # second call is a no-op
    assert "already seeded: c1 (no-op)" in capsys.readouterr().out
    assert len(OutcomeStore(store_path).all()) == 1


def test_cli_requires_arguments():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
