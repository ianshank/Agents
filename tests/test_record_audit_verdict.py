#!/usr/bin/env python3
"""Tests for scripts/record_audit_verdict.py — idempotent HUMAN_AUDIT wrapper (F-034)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import record_audit_verdict as rav
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

SHA = "a" * 40
SHORTSHA = "abc1234"


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
    store2 = _seed(path2, change_id=SHORTSHA)
    rc = rav.main(["--store", str(path2), "--change-id", SHORTSHA, "--incorrect"])
    assert rc == rav.EXIT_OK
    assert store2.resolved()[SHORTSHA].label is False


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


# --- selection propensity ----------------------------------------------------
def _seeded(tmp_path, name: str = "s.jsonl"):
    store = OutcomeStore(tmp_path / name)
    store.append(OutcomeRecord(SHA, "agent-core", 0.7, "2026-01-01T00:00:00+00:00"))
    return store


def test_record_stores_the_selection_propensity(tmp_path) -> None:
    store = _seeded(tmp_path)
    assert rav.record(str(store.path), SHA, True, "tester", selection_propensity=0.05) == 0
    assert store.resolved()[SHA].selection_propensity == 0.05


def test_record_without_a_propensity_leaves_it_unknown(tmp_path) -> None:
    """Omitted must stay NULL, never a fabricated probability."""
    store = _seeded(tmp_path)
    assert rav.record(str(store.path), SHA, True, "tester") == 0
    assert store.resolved()[SHA].selection_propensity is None


@pytest.mark.parametrize("bad", [1.5, 0.0, -0.1, float("nan"), float("inf")], ids=["gt1", "zero", "neg", "nan", "inf"])
def test_record_rejects_an_out_of_contract_propensity(tmp_path, bad) -> None:
    """Operator error (typed into a workflow dispatch): clean exit 2, nothing written."""
    store = _seeded(tmp_path, f"s{bad}.jsonl")
    assert rav.record(str(store.path), SHA, True, "tester", selection_propensity=bad) == 2
    assert store.resolved()[SHA].label is None


def test_cli_threads_the_propensity(tmp_path) -> None:
    store = _seeded(tmp_path)
    rc = rav.main(
        ["--store", str(store.path), "--change-id", SHA, "--correct", "--actor", "t", "--selection-propensity", "0.25"]
    )
    assert rc == 0
    assert store.resolved()[SHA].selection_propensity == 0.25


def test_cli_converts_a_write_boundary_rejection_into_exit_2(tmp_path, monkeypatch, caplog) -> None:
    """The store's own guard must surface as a clean exit 2, never a raw traceback.

    `record` screens the propensity with the same shared predicate, so this path is only
    reachable when the write boundary rejects something `record` let through. Forced here
    rather than left uncovered: it is the last line of defence for the store's contract.
    """
    store = _seeded(tmp_path)

    def _reject(*_a: object, **_k: object) -> None:
        raise ValueError("selection_propensity must be a finite number in (0, 1] (got 7.0)")

    monkeypatch.setattr(rav, "record_verdict", _reject)
    with caplog.at_level(logging.ERROR, logger="record_audit_verdict"):
        rc = rav.main(["--store", str(store.path), "--change-id", SHA, "--correct", "--actor", "t"])
    assert rc == 2
    assert any("finite number in (0, 1]" in r.getMessage() for r in caplog.records)


def test_an_injected_argument_is_rejected_as_one_token(tmp_path) -> None:
    """Guards the workflow's array expansion (see merge-gate-verdict.yml).

    The dispatch input reaches argparse as a SINGLE argument. If the workflow ever went
    back to an unquoted scalar it would word-split into a second `--store` that argparse
    resolves last-wins, redirecting the write. As one token, `type=float` refuses it.
    """
    store = _seeded(tmp_path)
    with pytest.raises(SystemExit) as exc:
        rav.main(
            [
                "--store",
                str(store.path),
                "--change-id",
                SHA,
                "--correct",
                "--selection-propensity",
                f"0.5 --store {tmp_path / 'evil.jsonl'}",
            ]
        )
    assert exc.value.code == 2, "argparse must reject a non-float, not accept a split"
    assert not (tmp_path / "evil.jsonl").exists()
