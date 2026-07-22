"""Tests for agent_core.calibration_report — agent-records calibration report (F-043)."""

from __future__ import annotations

import json

import pytest

from agent_core.calibration_report import (
    analyze_slice,
    build_report,
    is_agent_domain,
    main,
    render_json,
    render_markdown,
)
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

_TS = "2026-07-20T12:00:00+00:00"


def _seed(cid: str, domain: str, conf: float, av: str | None = None) -> OutcomeRecord:
    return OutcomeRecord(
        cid, domain, conf, _TS, label=None, label_source=None, labeled_at=None, agent_version=av
    )


def _labeled(cid: str, domain: str, conf: float, label: bool, source: LabelSource) -> OutcomeRecord:
    return OutcomeRecord(
        cid, domain, conf, _TS, label=label, label_source=source.value, labeled_at=_TS
    )


def _store(tmp_path, records: list[OutcomeRecord]) -> OutcomeStore:
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in records:
        store.append(r)
    return store


def _mixed_records() -> list[OutcomeRecord]:
    audit = LabelSource.HUMAN_AUDIT
    return [
        # agent domain: 3 human-audits (varying, both classes) + 1 passive
        _seed("c1", "agent-core", 0.8, "claude-code"),
        _labeled("c1", "agent-core", 0.8, True, audit),
        _seed("c2", "agent-core", 0.3, "claude-code"),
        _labeled("c2", "agent-core", 0.3, False, audit),
        _seed("c3", "agent-core", 0.6, "claude-code"),
        _labeled("c3", "agent-core", 0.6, True, audit),
        _seed("c4", "agent-core", 0.5, "claude-code"),
        _labeled("c4", "agent-core", 0.5, True, LabelSource.TIMEOUT_CLEAN),
        # human domain: constant 0.0 predictor, passive labels only
        _seed("h1", "human/eval-harness", 0.0),
        _labeled("h1", "human/eval-harness", 0.0, True, LabelSource.TIMEOUT_CLEAN),
        _seed("h2", "human/eval-harness", 0.0),
        _labeled("h2", "human/eval-harness", 0.0, False, LabelSource.CI_FAILURE),
    ]


# --- helpers ----------------------------------------------------------------
def test_is_agent_domain():
    assert is_agent_domain("agent-core") is True
    assert is_agent_domain("human/agent-core") is False


# --- analyze_slice ----------------------------------------------------------
def test_analyze_slice_non_degenerate():
    s = analyze_slice([(0.8, True), (0.3, False), (0.6, True), (0.2, False)], "x")
    assert s.n == 4
    assert s.n_correct == 2
    assert s.degenerate is None
    assert s.auroc is not None and 0.0 <= s.auroc <= 1.0
    assert s.base_rate_ci is not None and s.base_rate_ci[0] <= s.base_rate <= s.base_rate_ci[1]
    assert 0.0 <= s.abstention_at_target <= 1.0


def test_analyze_slice_constant_predictor_is_degenerate():
    s = analyze_slice([(0.5, True), (0.5, False), (0.5, True)], "x")
    assert s.auroc is None
    assert s.degenerate is not None and "constant predictor" in s.degenerate
    # ECE / Brier are still computed even when discrimination is undefined
    assert s.ece is not None and s.brier is not None


def test_analyze_slice_single_class_is_degenerate():
    s = analyze_slice([(0.8, True), (0.6, True), (0.4, True)], "x")
    assert s.auroc is None
    assert s.degenerate is not None and "single outcome class" in s.degenerate


def test_analyze_slice_empty():
    s = analyze_slice([], "x")
    assert s.n == 0
    assert s.degenerate == "no labeled records"
    assert s.auroc is None and s.base_rate is None


# --- build_report -----------------------------------------------------------
def _find(view, label):
    return next(s for s in view.slices if s.label == label)


def test_build_report_agent_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent")
    assert doc.total_records == 12
    assert doc.resolved_records == 6
    assert doc.by_label_source[LabelSource.HUMAN_AUDIT.value] == 3

    primary, diagnostic = doc.views
    assert primary.tau_eligible is True and diagnostic.tau_eligible is False

    agg = _find(primary, "ALL agent domains")
    assert agg.n == 3 and agg.degenerate is None and agg.auroc is not None

    # agent_version recovered by joining the audit record to its seed
    av = _find(primary, "agent_version: claude-code")
    assert av.n == 3

    # diagnostic adds the passive timeout_clean row
    assert _find(diagnostic, "ALL agent domains").n == 4


def test_build_report_human_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="human")
    primary, diagnostic = doc.views
    # no human_audit in human domains -> primary empty
    assert _find(primary, "ALL human domains").degenerate == "no labeled records"
    # diagnostic: two records, both raw_confidence 0.0 -> constant predictor
    diag = _find(diagnostic, "ALL human domains")
    assert diag.n == 2 and diag.auroc is None and "constant predictor" in diag.degenerate


def test_build_report_all_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="all")
    diag = _find(doc.views[1], "ALL all domains")
    assert diag.n == 6  # 4 agent + 2 human labeled


def test_build_report_missing_store(tmp_path):
    doc = build_report(OutcomeStore(tmp_path / "nope.jsonl"), domain_filter="agent")
    assert doc.total_records == 0 and doc.resolved_records == 0
    assert _find(doc.views[0], "ALL agent domains").n == 0


# --- rendering --------------------------------------------------------------
def test_render_markdown_has_caveat_and_note(tmp_path):
    md = render_markdown(build_report(_store(tmp_path, _mixed_records()), domain_filter="human"))
    assert "Agent-records calibration report" in md
    assert "deterministic proxy" in md  # honest caveat present
    assert "PRIMARY" in md and "DIAGNOSTIC" in md
    assert "constant predictor" in md  # degeneracy surfaced in the note column


def test_render_json_roundtrips(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent")
    parsed = json.loads(render_json(doc))
    assert parsed["domain_filter"] == "agent"
    assert parsed["views"][0]["tau_eligible"] is True


# --- CLI --------------------------------------------------------------------
def test_cli_markdown_stdout(tmp_path, capsys):
    store = _store(tmp_path, _mixed_records())
    rc = main(["--store", str(store.path), "--domain-filter", "agent"])
    assert rc == 0
    assert "Agent-records calibration report" in capsys.readouterr().out


def test_cli_json_to_file(tmp_path):
    store = _store(tmp_path, _mixed_records())
    out = tmp_path / "report.json"
    rc = main(["--store", str(store.path), "--format", "json", "--output", str(out)])
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["resolved_records"] == 6


def test_cli_rejects_bad_filter(tmp_path):
    with pytest.raises(SystemExit):
        main(["--store", str(tmp_path / "s.jsonl"), "--domain-filter", "bogus"])
