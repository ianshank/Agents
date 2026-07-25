#!/usr/bin/env python3
"""Tests for scripts/audit_issue_sync.py — audit-queue issue planning (F-034)."""

from __future__ import annotations

import json
import math
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


@pytest.mark.parametrize(
    "column",
    ["nan", "inf", "-inf", "0", "0.0", "1.5", "-0.2"],
    ids=["nan", "inf", "neg-inf", "zero", "zero-float", "above-one", "negative"],
)
def test_read_selected_rejects_an_out_of_contract_propensity(tmp_path, caplog, column) -> None:
    """`float()` parses "nan"/"inf"/any magnitude, so parsing is not validation.

    Each of these would otherwise render into the issue body and into a dispatch command
    that is guaranteed to fail at the recorder. Reject at ingestion; the change still gets
    audited, it just cannot be reweighted.
    """
    path = tmp_path / "selected.txt"
    path.write_text(f"sha1\t{column}\n", encoding="utf-8")
    with caplog.at_level("WARNING", logger="audit_issue_sync"):
        got = ais._read_selected(str(path))
    assert got == [ais.SelectedChange("sha1", None)]
    assert any("out-of-contract propensity" in r.message for r in caplog.records)


def test_read_selected_keeps_the_boundary_values_of_the_contract(tmp_path) -> None:
    """(0, 1] is half-open: 1.0 is a legitimate certainty, so it must survive."""
    path = tmp_path / "selected.txt"
    path.write_text("sha1\t1.0\nsha2\t0.000001\n", encoding="utf-8")
    assert ais._read_selected(str(path)) == [
        ais.SelectedChange("sha1", 1.0),
        ais.SelectedChange("sha2", 0.000001),
    ]


@pytest.mark.parametrize("value", [0.05, 1.0, 1e-7, 0.2 + 0.4], ids=["typical", "certain", "tiny", "noisy"])
def test_issue_body_carries_a_usable_propensity_into_the_dispatch_command(value) -> None:
    """The human copies the command out of the issue, so the value must travel *usably*.

    Asserts the round-trip rather than a literal string: the rendered text has to parse back
    to the same value and still satisfy the contract, which is the property that matters. A
    hardcoded `0.050000` would pass while `1e-7` silently rendered as `0.000000` — a command
    guaranteed to fail at the recorder.

    Equality is to the *rendered* precision, not bit-exact: 6 significant figures is a
    deliberate choice, trading ~1e-6 relative error (meaningless in a `1 / p` weight) for a
    number a human can read. `0.2 + 0.4` renders `0.6`, not `0.6000000000000001`.
    """
    rec = OutcomeRecord("sha1", "agent-core", 0.7, "2026-01-01T00:00:00+00:00")
    body = ais.issue_body(rec, "o/r", value)

    dispatch = next(ln for ln in body.splitlines() if "gh workflow run" in ln)
    sent = dispatch.split("selection_propensity=")[1].rstrip("`")
    assert math.isclose(float(sent), value, rel_tol=1e-6), f"dispatch carried {sent!r}, not {value!r}"
    assert ais.is_valid_propensity(float(sent)), "the copied value must still be usable"
    assert f"**selection_propensity**: `{sent}`" in body, "display and command must agree"


@pytest.mark.parametrize("bad", [0.0, 1.5, -0.1, float("nan"), float("inf")], ids=["zero", "gt1", "neg", "nan", "inf"])
def test_selected_change_enforces_the_contract_on_the_type(bad) -> None:
    """Construction is a second entry point; the guard belongs on the type, not one path.

    `_read_selected` screens the file, but a caller building one directly would otherwise
    smuggle an uninterpretable probability straight into an issue body.
    """
    with pytest.raises(ValueError, match=r"finite number in \(0, 1\]"):
        ais.SelectedChange("sha1", bad)


def test_selected_change_still_accepts_unknown() -> None:
    """Enforcing the contract must not outlaw the legitimate 'not captured' case."""
    assert ais.SelectedChange("sha1").propensity is None
    assert ais.SelectedChange("sha1", None).propensity is None
    assert ais.SelectedChange("sha1", 1.0).propensity == 1.0


def test_issue_body_omits_an_unknown_propensity_entirely() -> None:
    rec = OutcomeRecord("sha1", "agent-core", 0.7, "2026-01-01T00:00:00+00:00")
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
