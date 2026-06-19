"""Cover the remaining §7.2 behavioral checks and the validator CLI surface."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from forge import ground_truth, normalize, views
from forge import manifest as manifest_mod
from forge import package_validate as pv
from forge.atomic import write_package
from forge.package_validate import validate_package, write_validation_artifacts

PKG_VALIDATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "scripts", "forge", "package_validate.py")

FULL_RAW = {
    "prompt": "do it", "expected_outcome": {"ok": True}, "expected_output_fields": {"ok": True},
    "response": "done",
    "trace": {"tool_names": ["a", "b"], "tool_invocation_order": ["a", "b"], "retrieved_ids": ["d1"]},
    "completion_status": "success",
}


def _build(out_dir, raw=FULL_RAW, mode="full_dataset"):
    os.makedirs(out_dir, exist_ok=True)
    canonicals = [normalize.to_canonical(("evals/fixtures/full-dataset/records.jsonl", "1", raw))]
    gt = ground_truth.build_all(canonicals)
    view_data = views.build_views(canonicals)
    write_package(out_dir, canonicals=canonicals, ground_truth=gt, views=view_data,
                  provenance=[c["provenance"] for c in canonicals])
    m = manifest_mod.build_manifest(
        dataset_name="d", source_input="s", mode=mode,
        canonical_count=len(canonicals), ground_truth_count=len(gt), views=view_data,
        validation_status="pending",
    )
    _write_json(os.path.join(out_dir, "manifest.json"), m)
    return canonicals, gt, view_data


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _rewrite_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_first(path):
    with open(path, encoding="utf-8") as f:
        return json.loads(f.readline())


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def _truncate(path):
    with open(path, "w", encoding="utf-8"):
        pass


def _checks(errors):
    return {e["check"] for e in errors}


def test_nondeterministic_id_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    cpath = os.path.join(out, "canonical", "scenarios.jsonl")
    rec = _read_first(cpath)
    rec["scenario_id"] = "scn_tampered000000"  # still scn_ prefixed but wrong
    _rewrite_jsonl(cpath, [rec])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.nondeterministic_id" in _checks(errors)


def test_untraceable_provenance_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    cpath = os.path.join(out, "canonical", "scenarios.jsonl")
    rec = _read_first(cpath)
    rec["provenance"] = {"source_file": "", "locator": "1"}
    _rewrite_jsonl(cpath, [rec])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.untraceable_provenance" in _checks(errors)


def test_view_duplicates_canonical_detected(tmp_path):
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out)
    # write a retrieval view row that carries the full canonical schema
    full_row = dict(canonicals[0])
    full_row.pop("_raw", None)
    full_row["retrieved_ids"] = ["d1"]
    _rewrite_jsonl(os.path.join(out, "views", "retrieval_eval.jsonl"), [full_row])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.view_duplicates_canonical" in _checks(errors)


def test_view_not_unique_detected(tmp_path):
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out)
    sid = canonicals[0]["scenario_id"]
    row = {"scenario_id": sid, "retrieved_ids": ["d1"]}
    _rewrite_jsonl(os.path.join(out, "views", "retrieval_eval.jsonl"), [row, row])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.view_not_unique" in _checks(errors)


def test_tool_order_lost_detected(tmp_path):
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out)
    sid = canonicals[0]["scenario_id"]
    _rewrite_jsonl(os.path.join(out, "views", "tool_invocation_eval.jsonl"),
                   [{"scenario_id": sid, "tool_names": ["a", "b"], "tool_invocation_order": ["b", "a"]}])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.tool_order_lost" in _checks(errors)


def test_ground_truth_not_separate_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _canonicals, gt, _vd = _build(out)
    bad = dict(gt[0])
    bad["raw_prompt"] = "leaked"
    _rewrite_jsonl(os.path.join(out, "ground_truth", "mappings.jsonl"), [bad])
    passed, errors = validate_package(out)
    assert not passed and "behavioral.gt_not_separate" in _checks(errors)


def test_empty_view_mislabeled_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    # empty the retrieval view but leave manifest claiming it applicable
    _truncate(os.path.join(out, "views", "retrieval_eval.jsonl"))
    passed, errors = validate_package(out)
    checks = _checks(errors)
    assert not passed
    assert "behavioral.empty_view_mislabeled" in checks or "structural.applicability_contradiction" in checks


def test_bootstrap_fabrication_detected(tmp_path):
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out, mode="bootstrap")
    sid = canonicals[0]["scenario_id"]
    # inject a tool record under bootstrap mode and mark applicable to isolate the fabrication check
    _rewrite_jsonl(os.path.join(out, "views", "tool_invocation_eval.jsonl"),
                   [{"scenario_id": sid, "tool_names": ["a"], "tool_invocation_order": ["a"]}])
    mpath = os.path.join(out, "manifest.json")
    m = _read_json(mpath)
    m["view_applicability"]["tool_invocation_eval"] = {"applicable": True, "reason": None}
    m["counts"]["tool_invocation_eval_records"] = 1
    _write_json(mpath, m)
    passed, errors = validate_package(out)
    assert not passed and "behavioral.bootstrap_fabrication" in _checks(errors)


def test_missing_manifest_and_provenance_detected(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    os.remove(os.path.join(out, "manifest.json"))
    os.remove(os.path.join(out, "provenance", "source_index.jsonl"))
    passed, errors = validate_package(out)
    checks = _checks(errors)
    assert not passed
    assert "structural.missing_manifest" in checks
    assert "structural.missing_provenance" in checks


def test_write_validation_artifacts(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    passed, errors = validate_package(out)
    write_validation_artifacts(out, passed, errors)
    report = _read_json(os.path.join(out, "validation", "validation_report.json"))
    assert report["status"] == "passed" and report["error_count"] == 0
    assert os.path.exists(os.path.join(out, "validation", "schema_errors.jsonl"))


# --- CLI surface ---

def _cli(args):
    return subprocess.run([sys.executable, PKG_VALIDATE, *args], capture_output=True, text=True)


def test_cli_passes_on_good_package(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    r = _cli(["--out", out])
    assert r.returncode == 0 and "passed" in r.stdout


def test_cli_fails_on_broken_package(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    _truncate(os.path.join(out, "views", "retrieval_eval.jsonl"))  # mislabel
    r = _cli(["--out", out])
    assert r.returncode == 1 and "FAILED" in r.stdout


def test_cli_self_test_broken(tmp_path):
    r = _cli(["--self-test-broken", str(tmp_path / "broken")])
    assert r.returncode == 0 and "correctly rejected" in r.stdout


def test_cli_requires_an_argument():
    r = _cli([])
    assert r.returncode != 0


# --- in-process main() + remaining branches (coverage cannot see subprocesses) ---


def test_main_passes_in_process(tmp_path, monkeypatch):
    out = str(tmp_path / "pkg")
    _build(out)
    monkeypatch.setattr(sys, "argv", ["package_validate.py", "--out", out])
    assert pv.main() == 0


def test_main_self_test_in_process(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["package_validate.py", "--self-test-broken", str(tmp_path / "b")])
    assert pv.main() == 0


def test_main_no_args_errors(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["package_validate.py"])
    with pytest.raises(SystemExit):
        pv.main()


def test_main_reports_failure_in_process(tmp_path, monkeypatch, capsys):
    out = str(tmp_path / "pkg")
    _build(out)
    _truncate(os.path.join(out, "views", "retrieval_eval.jsonl"))  # mislabel -> fail
    monkeypatch.setattr(sys, "argv", ["package_validate.py", "--out", out])
    assert pv.main() == 1
    assert "FAILED" in capsys.readouterr().out


def test_structural_evidence_checks_fire(tmp_path):
    """View rows with a VALID scenario_id but missing the required evidence."""
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out)
    sid = canonicals[0]["scenario_id"]
    _rewrite_jsonl(os.path.join(out, "views", "retrieval_eval.jsonl"), [{"scenario_id": sid}])
    _rewrite_jsonl(os.path.join(out, "views", "tool_invocation_eval.jsonl"), [{"scenario_id": sid}])
    _rewrite_jsonl(os.path.join(out, "views", "response_eval.jsonl"), [{"scenario_id": sid}])
    _rewrite_jsonl(os.path.join(out, "views", "end_to_end_eval.jsonl"), [{"scenario_id": sid}])
    _, errors = validate_package(out)
    checks = _checks(errors)
    assert {"structural.retrieval_no_data", "structural.tool_no_data",
            "structural.response_no_target", "structural.e2e_no_target"} <= checks


def test_write_validation_artifacts_records_errors(tmp_path):
    out = str(tmp_path / "pkg")
    _build(out)
    _truncate(os.path.join(out, "views", "retrieval_eval.jsonl"))
    passed, errors = validate_package(out)
    write_validation_artifacts(out, passed, errors)
    lines = _read_lines(os.path.join(out, "validation", "schema_errors.jsonl"))
    assert len(lines) == len(errors) and len(lines) >= 1


def test_bootstrap_retrieval_fabrication_detected(tmp_path):
    out = str(tmp_path / "pkg")
    canonicals, _gt, _vd = _build(out, mode="bootstrap")
    sid = canonicals[0]["scenario_id"]
    _rewrite_jsonl(os.path.join(out, "views", "retrieval_eval.jsonl"),
                   [{"scenario_id": sid, "retrieved_ids": ["d1"]}])
    mpath = os.path.join(out, "manifest.json")
    m = _read_json(mpath)
    m["view_applicability"]["retrieval_eval"] = {"applicable": True, "reason": None}
    m["counts"]["retrieval_eval_records"] = 1
    _write_json(mpath, m)
    _, errors = validate_package(out)
    assert "behavioral.bootstrap_fabrication" in _checks(errors)
