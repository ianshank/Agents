#!/usr/bin/env python3
"""Tests for scripts/audit_issue_sync.py — audit-queue issue planning (F-034)."""

from __future__ import annotations

import json
from pathlib import Path

import audit_issue_sync as ais
import pytest
from agent_core.outcome_store import OutcomeRecord, OutcomeStore

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _store(tmp_path: Path, change_ids: list[str]) -> Path:
    path = tmp_path / "s.jsonl"
    store = OutcomeStore(path)
    for cid in change_ids:
        store.append(
            OutcomeRecord(
                change_id=cid,
                domain="human/agent-core",
                raw_confidence=0.0,
                merged_at="2026-01-01T00:00:00+00:00",
            )
        )
    return path


def test_title_roundtrip_and_foreign_titles_tolerated():
    issues = [
        {"title": ais.issue_title(SHA_A), "state": "OPEN"},
        {"title": ais.issue_title(SHA_B), "state": "CLOSED"},  # closed = handled
        {"title": "unrelated issue", "state": "OPEN"},
        {"state": "OPEN"},  # no title at all
    ]
    assert ais.audited_change_ids(issues) == {SHA_A, SHA_B}


def test_body_offers_only_synced_verdict_paths(tmp_path):
    store = OutcomeStore(_store(tmp_path, [SHA_A]))
    body = ais.issue_body(store.resolved()[SHA_A], repo="ianshank/Agents")
    assert f"gh workflow run {ais.VERDICT_WORKFLOW} -f change_id={SHA_A}" in body
    assert "Run workflow" in body  # Actions UI path
    assert "audit_sampler" not in body  # the local-store CLI would lose the verdict
    for context in (SHA_A, "human/agent-core", "2026-01-01T00:00:00+00:00", "pending"):
        assert context in body


def test_plan_skips_existing_and_unknown_ids(tmp_path, caplog):
    store = OutcomeStore(_store(tmp_path, [SHA_A, SHA_B]))
    existing = [{"title": ais.issue_title(SHA_B), "state": "CLOSED"}]
    plan = ais.plan_issues([SHA_A, SHA_B, SHA_C], store, existing, repo="o/r")
    assert [item["change_id"] for item in plan] == [SHA_A]
    assert plan[0]["title"] == ais.issue_title(SHA_A)


def test_main_end_to_end(tmp_path):
    store_path = _store(tmp_path, [SHA_A])
    selected = tmp_path / "selected.txt"
    selected.write_text(f"{SHA_A}\n\n", encoding="utf-8")
    existing = tmp_path / "issues.json"
    existing.write_text("[]", encoding="utf-8")
    output = tmp_path / "plan.json"
    rc = ais.main(
        [
            "--store",
            str(store_path),
            "--selected",
            str(selected),
            "--existing-issues",
            str(existing),
            "--repo",
            "o/r",
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    plan = json.loads(output.read_text(encoding="utf-8"))
    assert len(plan) == 1 and plan[0]["change_id"] == SHA_A


@pytest.mark.parametrize(
    "break_input",
    [
        lambda p: (p / "selected.txt").unlink(),  # unreadable selected
        lambda p: (p / "issues.json").write_text("{not json", encoding="utf-8"),
        lambda p: (p / "issues.json").write_text('{"a": 1}', encoding="utf-8"),  # non-list
    ],
)
def test_main_input_errors_exit_2(tmp_path, break_input):
    store_path = _store(tmp_path, [SHA_A])
    (tmp_path / "selected.txt").write_text(SHA_A + "\n", encoding="utf-8")
    (tmp_path / "issues.json").write_text("[]", encoding="utf-8")
    break_input(tmp_path)
    rc = ais.main(
        [
            "--store",
            str(store_path),
            "--selected",
            str(tmp_path / "selected.txt"),
            "--existing-issues",
            str(tmp_path / "issues.json"),
            "--repo",
            "o/r",
            "--output",
            str(tmp_path / "plan.json"),
        ]
    )
    assert rc == 2


# --- selection propensity ----------------------------------------------------
def test_read_selected_accepts_both_line_formats(tmp_path) -> None:
    """The sampler grew `--with-propensity`; an older selection file must still parse."""
    path = tmp_path / "selected.txt"
    path.write_text("sha1\t0.050000\nsha2\n", encoding="utf-8")
    got = ais._read_selected(str(path))
    assert got == [
        ais.SelectedChange("sha1", 0.05),
        ais.SelectedChange("sha2", None),
    ]


def test_read_selected_treats_a_malformed_propensity_as_unknown(tmp_path, caplog) -> None:
    """A bad probability column must not drop the change: it still deserves an audit.

    Unknown stays unknown rather than defaulting to a number, because inventing one
    would silently corrupt any later 1/p reweighting.
    """
    path = tmp_path / "selected.txt"
    path.write_text("sha1\tnot-a-number\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="audit_issue_sync"):
        got = ais._read_selected(str(path))
    assert got == [ais.SelectedChange("sha1", None)]
    assert any("unparseable propensity" in r.message for r in caplog.records)


def test_issue_body_carries_the_propensity_into_the_dispatch_command() -> None:
    """The human copies the command out of the issue, so the value must travel with it."""
    rec = OutcomeRecord("sha1", "agent-core", 0.7, "2026-01-01T00:00:00+00:00")
    with_p = ais.issue_body(rec, "o/r", 0.05)
    assert "**selection_propensity**: `0.050000`" in with_p
    assert "-f selection_propensity=0.050000" in with_p

    without = ais.issue_body(rec, "o/r", None)
    assert "selection_propensity" not in without, "unknown must not render a placeholder"


def test_plan_issues_accepts_bare_ids_and_selected_changes(tmp_path) -> None:
    """Both input shapes work, so a caller holding plain ids is unaffected."""
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(OutcomeRecord("sha1", "agent-core", 0.7, "2026-01-01T00:00:00+00:00"))
    bare = ais.plan_issues(["sha1"], store, [], "o/r")
    typed = ais.plan_issues([ais.SelectedChange("sha1", 0.05)], store, [], "o/r")
    assert [p["change_id"] for p in bare] == ["sha1"]
    assert "selection_propensity" not in bare[0]["body"]
    assert "selection_propensity" in typed[0]["body"]
