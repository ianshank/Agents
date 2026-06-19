"""Tests for the audit sampler."""

from __future__ import annotations

import random

import pytest

from agent_core.audit_sampler import AuditConfig, main, record_verdict, select_for_audit
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore


def _pending(cid: str, domain: str = "core") -> OutcomeRecord:
    return OutcomeRecord(
        change_id=cid, domain=domain, raw_confidence=0.9, merged_at="2026-01-01T00:00:00+00:00"
    )


def _store(tmp_path, *recs) -> OutcomeStore:
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in recs:
        store.append(r)
    return store


def test_select_honours_per_domain_floor(tmp_path):
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(5)])
    cfg = AuditConfig(base_rate=0.0, per_domain_floor=3)
    picked = select_for_audit(store, cfg, rng=random.Random(0))
    assert len(picked) == 3  # floor met purely by the per-domain floor, base_rate 0


def test_select_base_rate_adds_beyond_floor(tmp_path):
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(20)])
    cfg = AuditConfig(base_rate=1.0, per_domain_floor=0)
    picked = select_for_audit(store, cfg, rng=random.Random(0))
    assert len(picked) == 20  # base_rate 1.0 picks every candidate


def test_select_excludes_already_audited(tmp_path):
    audited = OutcomeRecord(
        change_id="a1",
        domain="core",
        raw_confidence=0.9,
        merged_at="2026-01-01T00:00:00+00:00",
        label=True,
        label_source=LabelSource.HUMAN_AUDIT.value,
        labeled_at="2026-01-02T00:00:00+00:00",
    )
    store = _store(tmp_path, audited, _pending("c1"))
    picked = select_for_audit(
        store, AuditConfig(base_rate=1.0, per_domain_floor=0), rng=random.Random(0)
    )
    assert "a1" not in picked and "c1" in picked


def test_record_verdict_writes_human_audit(tmp_path):
    store = _store(tmp_path, _pending("c1"))
    rec = record_verdict(store, "c1", correct=False, now=None)
    assert rec.label is False and rec.label_source == LabelSource.HUMAN_AUDIT.value
    assert store.resolved()["c1"].label_source == LabelSource.HUMAN_AUDIT.value


def test_record_verdict_unknown_id_raises(tmp_path):
    store = _store(tmp_path, _pending("c1"))
    with pytest.raises(KeyError):
        record_verdict(store, "nope", correct=True)


def test_main_select_and_record(tmp_path, capsys):
    store = _store(tmp_path, _pending("c1"))
    assert (
        main(
            ["--store", str(store.path), "select", "--base-rate", "1.0", "--per-domain-floor", "0"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "c1" in out
    assert main(["--store", str(store.path), "record", "--change-id", "c1", "--correct"]) == 0
    assert store.resolved()["c1"].label is True
