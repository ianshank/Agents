"""Tests for the outcome store, binning calibrator, and domain-model builder."""

from __future__ import annotations

import pytest

from agent_core.merge_gate import GatePolicyConfig
from agent_core.outcome_store import (
    BinningCalibrator,
    LabelSource,
    OutcomeRecord,
    OutcomeStore,
    _fold,
    _upper_half_ci_width,
    build_domain_models,
)

CFG = GatePolicyConfig()


def _rec(cid: str, domain: str, conf: float, label, source) -> OutcomeRecord:
    src = source.value if source else None
    return OutcomeRecord(
        change_id=cid,
        domain=domain,
        raw_confidence=conf,
        merged_at="2026-01-01T00:00:00+00:00",
        label=label,
        label_source=src,
        labeled_at="2026-01-02T00:00:00+00:00" if label is not None else None,
    )


# --- OutcomeRecord / OutcomeStore -------------------------------------------
def test_record_json_roundtrip():
    r = _rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT)
    assert OutcomeRecord.from_json(r.to_json()) == r


def test_record_agent_version_defaults_none_and_roundtrips():
    # New optional keying field defaults to None and survives a round-trip.
    r = _rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT)
    assert r.agent_version is None
    keyed = OutcomeRecord(
        change_id="c2",
        domain="sdlc",
        raw_confidence=0.8,
        merged_at="2026-01-01T00:00:00+00:00",
        agent_version="abc123",
    )
    assert OutcomeRecord.from_json(keyed.to_json()) == keyed
    assert keyed.agent_version == "abc123"


def test_record_loads_pre_1_3_0_json_without_agent_version():
    # A JSONL line written before the field existed must still construct (defaults None).
    legacy = (
        '{"change_id": "c1", "domain": "core", "raw_confidence": 0.9, '
        '"merged_at": "2026-01-01T00:00:00+00:00", "label": null, '
        '"label_source": null, "labeled_at": null}'
    )
    rec = OutcomeRecord.from_json(legacy)
    assert rec.agent_version is None
    assert rec.change_id == "c1"


def test_store_empty_returns_nothing(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    assert store.all() == []
    assert store.resolved() == {}


def test_store_append_and_all(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, None, None))
    store.append(_rec("c2", "core", 0.8, True, LabelSource.TIMEOUT_CLEAN))
    assert {r.change_id for r in store.all()} == {"c1", "c2"}


def test_store_all_skips_blank_lines(tmp_path):
    # all() streams the file line-by-line; blank/whitespace-only lines (e.g. a
    # stray trailing newline) must be skipped, not handed to json.loads.
    path = tmp_path / "s.jsonl"
    store = OutcomeStore(path)
    store.append(_rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT))
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n   \n")  # blank line + whitespace-only line
    assert [r.change_id for r in store.all()] == ["c1"]


def test_resolved_human_audit_wins(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.TIMEOUT_CLEAN))
    store.append(_rec("c1", "core", 0.9, False, LabelSource.HUMAN_AUDIT))
    assert store.resolved()["c1"].label_source == LabelSource.HUMAN_AUDIT.value


def test_resolved_audit_not_overwritten_by_passive(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT))
    store.append(_rec("c1", "core", 0.9, False, LabelSource.REVERT))
    assert store.resolved()["c1"].label is True  # audit kept


def test_resolved_latest_labeled_wins_among_passive(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.TIMEOUT_CLEAN))
    store.append(_rec("c1", "core", 0.9, False, LabelSource.CI_FAILURE))
    assert store.resolved()["c1"].label_source == LabelSource.CI_FAILURE.value


# --- BinningCalibrator -------------------------------------------------------
def test_binning_calibrator_fit_predict():
    scores = [0.05, 0.15, 0.95, 0.96]
    labels = [False, False, True, True]
    cal = BinningCalibrator.fit(scores, labels)
    assert cal.predict(0.05) == 0.0  # bottom bin: all incorrect
    assert cal.predict(0.95) == 1.0  # top bin: all correct
    assert cal.predict(1.0) == 1.0  # >= top edge -> final return
    assert cal.predict(0.45) == 0.0  # empty bin -> 0.0


def test_binning_calibrator_bin_index_distinguishes_equal_accuracy_bins():
    # Two distinct bins both with 100% accuracy must NOT share a bin index.
    scores = [0.85, 0.95]
    labels = [True, True]
    cal = BinningCalibrator.fit(scores, labels)
    assert cal.predict(0.85) == cal.predict(0.95) == 1.0  # same accuracy
    assert cal.bin_index(0.85) != cal.bin_index(0.95)  # but different bins
    assert cal.bin_index(1.0) == len(cal.bin_acc) - 1


def test_upper_half_ci_width_empty_and_nonempty():
    assert _upper_half_ci_width([], [], 1.96) == 0.0
    width = _upper_half_ci_width([0.95, 0.96, 0.97], [True, True, False], 1.96)
    assert 0.0 < width <= 1.0


def test_fold_is_deterministic():
    assert _fold("abc") == _fold("abc")
    assert _fold("abc") in (0, 1)


# --- build_domain_models -----------------------------------------------------
def _id_for_fold(fold: int) -> str:
    i = 0
    while True:
        cid = f"x{i}"
        if _fold(cid) == fold:
            return cid
        i += 1


def test_build_models_healthy_domain_gets_tau(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    # ~1000 audits: high confidence => correct, low => incorrect (cleanly
    # separable). The held-out fold needs enough top-bin samples for the Wilson
    # lower bound to clear the 2% risk target (see ADR 0005 sample-size note).
    for i in range(1000):
        high = i % 2 == 0
        store.append(
            _rec(
                f"c{i}",
                "core",
                0.96 if high else 0.04,
                high,
                LabelSource.HUMAN_AUDIT,
            )
        )
    models = build_domain_models(store, CFG)
    assert "core" in models
    m = models["core"]
    assert m.health.n == 1000
    assert m.health.is_trustworthy(CFG)
    assert m.tau is not None


def test_build_models_thin_domain_has_no_tau(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    for i in range(5):
        store.append(_rec(f"u{i}", "ui", 0.9, True, LabelSource.HUMAN_AUDIT))
    m = build_domain_models(store, CFG)["ui"]
    assert m.health.n == 5
    assert m.tau is None  # untrustworthy => not eligible


def test_build_models_single_record_folds_fall_back(tmp_path):
    # Single-record domains exercise the "empty fold -> use all records" fallback
    # for both fold 0 (eval empty) and fold 1 (fit empty).
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec(_id_for_fold(0), "d0", 0.9, True, LabelSource.HUMAN_AUDIT))
    store.append(_rec(_id_for_fold(1), "d1", 0.9, True, LabelSource.HUMAN_AUDIT))
    models = build_domain_models(store, CFG)
    assert models["d0"].tau is None and models["d1"].tau is None


def test_build_models_ignores_passive_labels(tmp_path):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.TIMEOUT_CLEAN))
    assert build_domain_models(store, CFG) == {}


def test_build_models_reports_why_records_were_excluded(tmp_path, caplog):
    """The exclusion is correct but was invisible: an all-passive store looks like an
    empty one from the outside (no models, no tau). It has to say which it is."""
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.TIMEOUT_CLEAN))
    store.append(_rec("c2", "core", 0.8, False, LabelSource.CI_FAILURE))
    store.append(_rec("c3", "core", 0.7, None, None))  # merged, not yet labelled
    with caplog.at_level("INFO", logger="agent_core.outcome_store"):
        assert build_domain_models(store, CFG) == {}
    logged = "\n".join(r.message for r in caplog.records)
    assert "passive:timeout_clean=1" in logged
    assert "passive:ci_failure=1" in logged
    assert "unlabelled=1" in logged
    assert "no HUMAN_AUDIT records available" in logged


def test_build_models_does_not_warn_when_audit_records_exist(tmp_path, caplog):
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(_rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT))
    with caplog.at_level("INFO", logger="agent_core.outcome_store"):
        assert build_domain_models(store, CFG) != {}
    assert not any("no HUMAN_AUDIT records available" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf"), 1.5, 5.0, -0.1],
    ids=["nan", "inf", "-inf", "just-above-1", "far-above-1", "below-0"],
)
def test_bin_index_floors_out_of_contract_scores(bad, caplog):
    """An out-of-contract score must never read as the highest-confidence bucket.

    `NaN < edge` is False for every edge and `inf` exceeds them all, so both fell
    through the scan to the `score >= top edge` return -- scoring garbage as maximum
    confidence; anything above 1.0 did the same. Records reach this method straight
    from the store, where OutcomeRecord applies no validation and ChangeContext's
    check is bypassed.
    """
    cal = BinningCalibrator.fit([0.05] * 10 + [0.95] * 10, [False] * 10 + [True] * 10)
    assert cal.bin_index(0.95) == 9  # sanity: real high confidence still lands high
    with caplog.at_level("WARNING", logger="agent_core.outcome_store"):
        assert cal.bin_index(bad) == 0
    assert cal.predict(bad) == cal.bin_acc[0]
    assert any("out-of-contract raw_score" in r.message for r in caplog.records)


def test_bin_index_boundaries_are_unchanged():
    """The fail-closed NaN branch must not perturb ordinary routing."""
    cal = BinningCalibrator.fit([0.5], [True])
    assert cal.bin_index(0.0) == 0
    assert cal.bin_index(0.55) == 5
    assert cal.bin_index(1.0) == 9  # exactly the top edge is in contract -> top bin


# --- forward compatibility (ADR 0025) ----------------------------------------
def test_from_json_tolerates_fields_a_newer_writer_added(caplog):
    """An unknown field is additive schema evolution, not corruption."""
    line = (
        '{"change_id": "c1", "domain": "core", "raw_confidence": 0.9, '
        '"merged_at": "2026-01-01T00:00:00+00:00", "label": null, "label_source": null, '
        '"labeled_at": null, "agent_version": null, "future_field": "from a newer writer"}'
    )
    with caplog.at_level("WARNING", logger="agent_core.outcome_store"):
        rec = OutcomeRecord.from_json(line)
    assert rec.change_id == "c1" and rec.raw_confidence == 0.9
    assert not hasattr(rec, "future_field")  # dropped in memory, never invented
    logged = "\n".join(r.message for r in caplog.records)
    assert "future_field" in logged and "c1" in logged


@pytest.mark.parametrize(
    ("line", "exc", "why"),
    [
        ("{not json at all", ValueError, "malformed JSON"),
        ('["a", "list"]', TypeError, "non-object payload"),
        ('{"domain": "core", "raw_confidence": 0.9}', TypeError, "missing required field"),
    ],
    ids=["malformed-json", "non-object", "missing-required"],
)
def test_from_json_still_raises_on_corruption(line, exc, why):
    """Tolerating unknown fields must not weaken strictness about corruption."""
    with pytest.raises(exc):
        OutcomeRecord.from_json(line)


def test_store_sync_opaque_line_is_readable_by_outcome_store(tmp_path, caplog):
    """The seam neither module's suite crossed.

    store_sync preserves a line carrying a newer writer's field verbatim, so that a
    pull/push never rewrites history it does not own. OutcomeStore used to raise
    TypeError on that exact line, which would fail the gate on every PR. Both sides
    must now hold at once: preserved on write, readable on read.
    """
    from agent_core.store_sync import read_store_lines

    path = tmp_path / "s.jsonl"
    path.write_text(
        _rec("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT).to_json() + "\n"
        '{"change_id": "c2", "domain": "core", "raw_confidence": 0.8, '
        '"merged_at": "2026-01-01T00:00:00+00:00", "tomorrows_field": 1}\n',
        encoding="utf-8",
    )
    # store_sync still classifies it as opaque and keeps it verbatim.
    records, opaque = read_store_lines(path)
    assert len(records) == 1 and len(opaque) == 1
    assert "tomorrows_field" in opaque[0]

    # OutcomeStore now reads the whole file instead of raising.
    with caplog.at_level("WARNING", logger="agent_core.outcome_store"):
        loaded = OutcomeStore(path).all()
    assert [r.change_id for r in loaded] == ["c1", "c2"]
    assert any("tomorrows_field" in r.message for r in caplog.records)


# --- selection propensity (forward/backward compatibility) -------------------
def test_selection_propensity_round_trips() -> None:
    rec = OutcomeRecord(
        change_id="c1",
        domain="core",
        raw_confidence=0.9,
        merged_at="2026-01-01T00:00:00+00:00",
        label=True,
        label_source=LabelSource.HUMAN_AUDIT.value,
        labeled_at="2026-01-02T00:00:00+00:00",
        selection_propensity=0.05,
    )
    assert OutcomeRecord.from_json(rec.to_json()) == rec


def test_record_written_before_the_field_existed_loads_as_none() -> None:
    """Old lines carry no propensity key; they must load, not raise, and stay unknown."""
    legacy = (
        '{"change_id": "c1", "domain": "core", "raw_confidence": 0.9, '
        '"merged_at": "2026-01-01T00:00:00+00:00", "label": true, '
        '"label_source": "human_audit", "labeled_at": "2026-01-02T00:00:00+00:00", '
        '"agent_version": null}'
    )
    rec = OutcomeRecord.from_json(legacy)
    assert rec.change_id == "c1"
    assert rec.selection_propensity is None  # unknown, never silently 0.0 or 1.0


def test_propensity_absent_records_still_build_domain_models(tmp_path) -> None:
    """The new field must not become a hidden precondition of the calibration fit."""
    store = OutcomeStore(tmp_path / "s.jsonl")
    for i in range(4):
        store.append(_rec(f"c{i}", "core", 0.1 + 0.2 * i, i % 2 == 0, LabelSource.HUMAN_AUDIT))
    assert set(build_domain_models(store, CFG)) == {"core"}
