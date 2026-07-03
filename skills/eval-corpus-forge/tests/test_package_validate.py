"""Unit tests for forge.package_validate: every major §7 check must actually fire."""

from __future__ import annotations

import json
import os

from forge import ground_truth, normalize, views
from forge import manifest as manifest_mod
from forge.atomic import write_package
from forge.package_validate import _self_test_broken, validate_package


def _build_good_package(out_dir, raw):
    os.makedirs(out_dir, exist_ok=True)
    canonicals = [normalize.to_canonical(("evals/fixtures/full-dataset/records.jsonl", "1", raw))]
    gt = ground_truth.build_all(canonicals)
    view_data = views.build_views(canonicals)
    write_package(
        out_dir,
        canonicals=canonicals,
        ground_truth=gt,
        views=view_data,
        provenance=[c["provenance"] for c in canonicals],
    )
    m = manifest_mod.build_manifest(
        dataset_name="d",
        source_input="s",
        mode="full_dataset",
        canonical_count=len(canonicals),
        ground_truth_count=len(gt),
        views=view_data,
        validation_status="pending",
    )
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f)
    return view_data


FULL_RAW = {
    "prompt": "do it",
    "expected_outcome": {"ok": True},
    "expected_output_fields": {"ok": True},
    "response": "done",
    "trace": {"tool_names": ["a", "b"], "tool_invocation_order": ["a", "b"], "retrieved_ids": ["d1"]},
    "completion_status": "success",
}


def _checks(errors):
    return {e["check"] for e in errors}


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_first(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(f.readline())


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_good_package_passes(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    passed, errors = validate_package(out)
    assert passed, errors


def test_count_mismatch_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    mpath = os.path.join(out, "manifest.json")
    m = _read_json(mpath)
    m["counts"]["canonical_scenarios"] = 999
    _write_json(mpath, m)
    passed, errors = validate_package(out)
    assert not passed and "structural.count_mismatch" in _checks(errors)


def test_dangling_view_reference_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    vpath = os.path.join(out, "views", "retrieval_eval.jsonl")
    with open(vpath, "a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario_id": "scn_ghost", "retrieved_ids": ["z"]}) + "\n")
    passed, errors = validate_package(out)
    # count mismatch and dangling ref both fire; the dangling one is the point
    assert not passed and "structural.view_dangling" in _checks(errors)


def test_missing_required_field_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    cpath = os.path.join(out, "canonical", "scenarios.jsonl")
    rec = _read_first(cpath)
    del rec["expected_intent"]
    with open(cpath, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    passed, errors = validate_package(out)
    assert not passed and "structural.missing_field" in _checks(errors)


def test_malformed_json_recorded_not_crashed(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    with open(os.path.join(out, "canonical", "scenarios.jsonl"), "w", encoding="utf-8") as f:
        f.write("{not valid json\n")
    passed, errors = validate_package(out)  # must not raise
    assert not passed and "structural.malformed_json" in _checks(errors)


def test_applicability_contradiction_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    mpath = os.path.join(out, "manifest.json")
    m = _read_json(mpath)
    m["view_applicability"]["retrieval_eval"]["applicable"] = False  # but rows exist
    _write_json(mpath, m)
    passed, errors = validate_package(out)
    assert not passed and "structural.applicability_contradiction" in _checks(errors)


def test_self_test_broken_returns_zero(tmp_path):
    # the negative self-test must report the validator correctly rejected a corrupt package
    assert _self_test_broken(str(tmp_path / "broken")) == 0


def test_unhashable_scenario_ids_reported_not_crashed(tmp_path):
    """List/dict ids from malformed JSON must become validation errors, not TypeErrors."""
    out = str(tmp_path / "pkg")
    _build_good_package(out, FULL_RAW)
    # Corrupt the package: a canonical row with a list id, a view row with a dict id.
    with open(os.path.join(out, "canonical", "scenarios.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario_id": ["not", "a", "string"], "raw_prompt": "x"}) + "\n")
    with open(os.path.join(out, "views", "response_eval.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario_id": {"bad": 1}, "response": "r", "comparison_target": "t"}) + "\n")
    ok, errors = validate_package(out)  # must not raise
    assert ok is False
    checks = _checks(errors)
    assert "structural.invalid_scenario_id" in checks
    assert "structural.view_dangling" in checks
