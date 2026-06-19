"""Tests for the passive outcome labeller."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_core.outcome_labeller import LabellerConfig, label_matured, main
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
CFG = LabellerConfig(maturity_days=7)


class _Reverts:
    def __init__(self, ids: set[str]) -> None:
        self._ids = ids

    def was_reverted(self, change_id: str, since: datetime) -> bool:
        return change_id in self._ids


class _Failures:
    def __init__(self, ids: set[str]) -> None:
        self._ids = ids

    def caused_failure(self, change_id: str, since: datetime) -> bool:
        return change_id in self._ids


def _pending(cid: str, merged: str) -> OutcomeRecord:
    return OutcomeRecord(change_id=cid, domain="core", raw_confidence=0.9, merged_at=merged)


def _store(tmp_path, *recs):
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in recs:
        store.append(r)
    return store


def test_revert_labels_incorrect(tmp_path):
    store = _store(tmp_path, _pending("c1", "2026-05-01T00:00:00+00:00"))
    out = label_matured(store, _Reverts({"c1"}), _Failures(set()), CFG, now=NOW)
    assert out[0].label is False and out[0].label_source == LabelSource.REVERT.value


def test_failure_labels_incorrect(tmp_path):
    store = _store(tmp_path, _pending("c1", "2026-05-01T00:00:00+00:00"))
    out = label_matured(store, _Reverts(set()), _Failures({"c1"}), CFG, now=NOW)
    assert out[0].label_source == LabelSource.CI_FAILURE.value


def test_timeout_clean_labels_correct(tmp_path):
    store = _store(tmp_path, _pending("c1", "2026-05-01T00:00:00+00:00"))  # >7 days old
    out = label_matured(store, _Reverts(set()), _Failures(set()), CFG, now=NOW)
    assert out[0].label is True and out[0].label_source == LabelSource.TIMEOUT_CLEAN.value


def test_not_yet_matured_is_skipped(tmp_path):
    store = _store(tmp_path, _pending("c1", "2026-05-30T00:00:00+00:00"))  # 2 days old
    assert label_matured(store, _Reverts(set()), _Failures(set()), CFG, now=NOW) == []


def test_already_labelled_is_skipped(tmp_path):
    labelled = OutcomeRecord(
        change_id="c1",
        domain="core",
        raw_confidence=0.9,
        merged_at="2026-05-01T00:00:00+00:00",
        label=True,
        label_source=LabelSource.HUMAN_AUDIT.value,
        labeled_at="2026-05-02T00:00:00+00:00",
    )
    store = _store(tmp_path, labelled)
    assert label_matured(store, _Reverts(set()), _Failures(set()), CFG, now=NOW) == []


def test_label_matured_default_now(tmp_path):
    # Exercise the now=None default branch (record far in the past matures).
    store = _store(tmp_path, _pending("c1", "2000-01-01T00:00:00+00:00"))
    out = label_matured(store, _Reverts(set()), _Failures(set()), CFG)
    assert out and out[0].label_source == LabelSource.TIMEOUT_CLEAN.value


def test_main_runs_with_placeholder_detectors(tmp_path):
    store = _store(tmp_path, _pending("c1", "2000-01-01T00:00:00+00:00"))
    rc = main(["--store", str(store.path), "--maturity-days", "7"])
    assert rc == 0
    # placeholder detectors never revert/fail, so the matured change is TIMEOUT_CLEAN
    assert any(r.label_source == LabelSource.TIMEOUT_CLEAN.value for r in store.all())
