"""Tests for scripts/migrations/agent_domain_backfill.py (F-044) — pure backfill logic."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(str(_ROOT), "scripts", "migrations"))

import agent_domain_backfill as adb  # noqa: E402
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore  # noqa: E402

_TS = "2026-07-20T12:00:00+00:00"
_PROXY = str(_ROOT / "config" / "agent-confidence.yaml")


def _rec(cid, domain, conf, source=None, label=None):
    return OutcomeRecord(
        cid, domain, conf, _TS, label=label, label_source=(source.value if source else None), labeled_at=None
    )


# --- pure helpers -----------------------------------------------------------
def test_strip_human_namespace():
    assert adb.strip_human_namespace("human/agent-core") == "agent-core"
    assert adb.strip_human_namespace("agent-core") == "agent-core"


def test_parse_shas_file():
    text = "# header\n\nabc123 claude-code\n def456  \n  # comment\nghi789 devin\n"
    parsed = adb.parse_shas_file(text)
    assert parsed == {"abc123": "claude-code", "def456": "claude-code", "ghi789": "devin"}


def test_render_diff_empty():
    assert "no changes" in adb.render_diff([])


# --- plan_backfill ----------------------------------------------------------
def test_plan_backfill_redomains_all_records_of_target():
    records = [
        _rec("c1", "human/agent-core", 0.0),
        _rec("c1", "human/agent-core", 0.0, LabelSource.TIMEOUT_CLEAN, True),
        _rec("c2", "human/eval-harness", 0.0),  # untargeted
    ]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    new, diffs = adb.plan_backfill(records, targets)
    c1 = [r for r in new if r.change_id == "c1"]
    assert all(r.domain == "agent-core" and r.raw_confidence == 0.8 and r.agent_version == "claude-code" for r in c1)
    # the passive label is preserved, only the domain/confidence/version change
    assert any(r.label_source == LabelSource.TIMEOUT_CLEAN.value for r in c1)
    # untargeted record untouched
    assert next(r for r in new if r.change_id == "c2").domain == "human/eval-harness"
    assert len(diffs) == 2


def test_plan_backfill_is_idempotent():
    records = [_rec("c1", "human/agent-core", 0.0)]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    once, _ = adb.plan_backfill(records, targets)
    twice, diffs = adb.plan_backfill(once, targets)
    assert twice == once
    assert diffs == []  # nothing left to change


def test_plan_backfill_refuses_human_audit():
    records = [_rec("c1", "human/agent-core", 0.0, LabelSource.HUMAN_AUDIT, True)]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    with pytest.raises(ValueError, match="HUMAN_AUDIT"):
        adb.plan_backfill(records, targets)


# --- CLI (git-free via monkeypatched confidence) ----------------------------
def _seed_store(tmp_path, records):
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in records:
        store.append(r)
    return store


def _shas_file(tmp_path, ids):
    p = tmp_path / "shas.txt"
    p.write_text("".join(f"{i} claude-code\n" for i in ids), encoding="utf-8")
    return str(p)


def test_main_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(adb, "compute_confidence_for", lambda cid, repo_dir, proxy: 0.7)
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0), _rec("c2", "human/docs", 0.0)])
    before = store.path.read_text(encoding="utf-8")
    rc = adb.main(["--store", str(store.path), "--shas-file", _shas_file(tmp_path, ["c1"]), "--proxy-config", _PROXY])
    assert rc == 0
    assert store.path.read_text(encoding="utf-8") == before  # untouched
    assert not (tmp_path / "s.jsonl.pre-backfill.bak").exists()
    assert "agent-core" in capsys.readouterr().out


def test_main_apply_rewrites_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "compute_confidence_for", lambda cid, repo_dir, proxy: 0.7)
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0), _rec("c2", "human/docs", 0.0)])
    rc = adb.main(
        ["--store", str(store.path), "--shas-file", _shas_file(tmp_path, ["c1"]), "--proxy-config", _PROXY, "--apply"]
    )
    assert rc == 0
    assert (tmp_path / "s.jsonl.pre-backfill.bak").exists()
    resolved = {r.change_id: r for r in OutcomeStore(store.path).all()}
    assert resolved["c1"].domain == "agent-core" and resolved["c1"].raw_confidence == 0.7
    assert resolved["c1"].agent_version == "claude-code"
    assert resolved["c2"].domain == "human/docs"  # untargeted, unchanged
