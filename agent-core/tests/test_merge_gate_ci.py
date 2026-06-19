"""Tests for the merge-gate CI entrypoint."""

from __future__ import annotations

import json

import pytest

from agent_core import merge_gate_ci
from agent_core.merge_gate import ChangeContext, GateDecision, GatePolicyConfig
from agent_core.merge_gate_ci import main, run
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

CFG = GatePolicyConfig()


def _healthy_store(path) -> OutcomeStore:
    store = OutcomeStore(path)
    for i in range(1000):
        high = i % 2 == 0
        store.append(
            OutcomeRecord(
                change_id=f"c{i}",
                domain="core",
                raw_confidence=0.96 if high else 0.04,
                merged_at="2026-01-01T00:00:00+00:00",
                label=high,
                label_source=LabelSource.HUMAN_AUDIT.value,
                labeled_at="2026-01-02T00:00:00+00:00",
            )
        )
    return store


def _ctx(**kw) -> ChangeContext:
    base = dict(mech_pass=True, touches_protected=False, raw_confidence=0.96, domain="core")
    base.update(kw)
    return ChangeContext(**base)


def test_run_cold_start_escalates(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    d, why = run(_ctx(domain="unknown"), store, CFG)
    assert d == GateDecision.ESCALATE
    assert "cold start" in why


def test_run_reject_on_mech_fail(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, _ = run(_ctx(mech_pass=False), store, CFG)
    assert d == GateDecision.REJECT


def test_run_protected_escalates(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, _ = run(_ctx(touches_protected=True), store, CFG)
    assert d == GateDecision.ESCALATE


def test_run_auto_merge_on_healthy_high_confidence(tmp_path):
    store = _healthy_store(tmp_path / "s.jsonl")
    d, why = run(_ctx(), store, CFG)
    assert d == GateDecision.AUTO_MERGE
    assert "tau=" in why


def test_run_bin_conflation_avoided(tmp_path):
    # A lone audit in a different high bin (0.85) must not piggyback on the
    # well-populated 0.96 bin: grouping by bin index keeps it thin -> ESCALATE.
    store = _healthy_store(tmp_path / "s.jsonl")
    store.append(
        OutcomeRecord(
            change_id="lone",
            domain="core",
            raw_confidence=0.85,
            merged_at="2026-01-01T00:00:00+00:00",
            label=True,
            label_source=LabelSource.HUMAN_AUDIT.value,
            labeled_at="2026-01-02T00:00:00+00:00",
        )
    )
    d, _ = run(_ctx(raw_confidence=0.85), store, CFG)
    assert d == GateDecision.ESCALATE


def test_main_exit_codes_via_argv(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    assert (
        main(["--store", store_path, "--mech-pass", "--raw-confidence", "0.96", "--domain", "core"])
        == 0
    )
    assert main(["--store", store_path, "--no-mech-pass", "--domain", "core"]) == 20
    assert main(["--store", store_path, "--mech-pass", "--domain", "unknown"]) == 10


def test_main_with_context_file_and_audit_log(tmp_path):
    store_path = str(_healthy_store(tmp_path / "s.jsonl").path)
    ctx_file = tmp_path / "ctx.json"
    ctx_file.write_text(
        json.dumps(
            {
                "mech_pass": True,
                "touches_protected": False,
                "raw_confidence": 0.96,
                "domain": "core",
            }
        ),
        encoding="utf-8",
    )
    audit = tmp_path / "audit.jsonl"
    rc = main(["--store", store_path, "--context", str(ctx_file), "--audit-log", str(audit)])
    assert rc == 0
    line = json.loads(audit.read_text(encoding="utf-8").strip())
    assert line["decision"] == "auto_merge" and line["domain"] == "core"


def test_main_internal_error_returns_one(tmp_path):
    # --context points at a missing file -> read raises -> caught -> exit 1.
    rc = main(["--store", str(tmp_path / "s.jsonl"), "--context", str(tmp_path / "missing.json")])
    assert rc == 1


def test_main_missing_store_is_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_exit_table_covers_all_decisions():
    assert set(merge_gate_ci.EXIT) == set(GateDecision)
