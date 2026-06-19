"""§7 package validation: structural + behavioral checks on a written package.

This is the domain validator (distinct from the framework's validate_skill.py). It reads the
package back from disk, runs every §7 check, writes validation artifacts, and returns a
status. The framework eval asserts on its results, and a negative self-test proves it
actually rejects malformed packages (revision 2).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from forge.normalize import scenario_id

REQUIRED_SCENARIO_FIELDS = (
    "scenario_id",
    "session_id",
    "turn_id",
    "raw_prompt",
    "task_context",
    "expected_intent",
    "expected_outcome",
    "provenance",
    "trace",
    "metadata",
)
VIEW_FILES = ("retrieval_eval", "tool_invocation_eval", "response_eval", "end_to_end_eval")


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_json(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_package(out_dir: str) -> tuple[bool, list[dict[str, Any]]]:
    """Run all §7 checks. Returns (passed, errors) where errors are structured records."""
    errors: list[dict[str, Any]] = []

    def fail(check: str, detail: str, scenario: str | None = None) -> None:
        errors.append({"check": check, "detail": detail, "scenario_id": scenario})

    manifest = _read_json(os.path.join(out_dir, "manifest.json"))
    canonical = _read_jsonl(os.path.join(out_dir, "canonical", "scenarios.jsonl"))
    ground_truth = _read_jsonl(os.path.join(out_dir, "ground_truth", "mappings.jsonl"))
    views = {name: _read_jsonl(os.path.join(out_dir, "views", f"{name}.jsonl")) for name in VIEW_FILES}

    # --- §7.1 structural ---
    if not canonical:
        fail("structural.no_canonical", "no canonical scenarios produced")
    scenario_ids: set[str] = set()
    for sc in canonical:
        sid = sc.get("scenario_id")
        for field in REQUIRED_SCENARIO_FIELDS:
            if field not in sc:
                fail("structural.missing_field", f"canonical scenario missing field {field!r}", sid)
        scenario_ids.add(sid)

    # manifest presence + count cross-check (independent re-count from disk, revision 3)
    if manifest is None:
        fail("structural.missing_manifest", "manifest.json is missing")
    else:
        counts = manifest.get("counts", {})
        disk_counts = {
            "canonical_scenarios": len(canonical),
            "ground_truth_mappings": len(ground_truth),
            "retrieval_eval_records": len(views["retrieval_eval"]),
            "tool_invocation_eval_records": len(views["tool_invocation_eval"]),
            "response_eval_records": len(views["response_eval"]),
            "end_to_end_eval_records": len(views["end_to_end_eval"]),
        }
        for key, disk_val in disk_counts.items():
            if counts.get(key) != disk_val:
                fail("structural.count_mismatch", f"{key}: manifest={counts.get(key)} disk={disk_val}")

    # validation artifacts exist
    if not os.path.isfile(os.path.join(out_dir, "provenance", "source_index.jsonl")):
        fail("structural.missing_provenance", "provenance/source_index.jsonl is missing")

    # ground-truth references valid scenarios
    for gt in ground_truth:
        if gt.get("scenario_id") not in scenario_ids:
            fail("structural.gt_dangling", f"ground-truth references unknown scenario {gt.get('scenario_id')!r}", gt.get("scenario_id"))

    # view records reference valid scenarios and carry required evidence
    for name, rows in views.items():
        for row in rows:
            sid = row.get("scenario_id")
            if sid not in scenario_ids:
                fail("structural.view_dangling", f"{name} references unknown scenario {sid!r}", sid)
            if name == "retrieval_eval" and not (row.get("retrieved_ids") or row.get("retrieved_entities")):
                fail("structural.retrieval_no_data", "retrieval view record without retrieval data", sid)
            if name == "tool_invocation_eval" and not row.get("tool_names"):
                fail("structural.tool_no_data", "tool view record without tool-call data", sid)
            if name == "response_eval" and not (row.get("response") and row.get("comparison_target")):
                fail("structural.response_no_target", "response view record without response+comparison target", sid)
            if name == "end_to_end_eval" and not row.get("success_target"):
                fail("structural.e2e_no_target", "end-to-end view record without success target", sid)

    # applicability must not contradict data
    if manifest is not None:
        for name in VIEW_FILES:
            applicable = manifest.get("view_applicability", {}).get(name, {}).get("applicable")
            has_rows = len(views[name]) > 0
            if applicable != has_rows:
                fail("structural.applicability_contradiction", f"{name}: applicable={applicable} but rows={has_rows}")

    # --- §7.2 behavioral ---
    by_id = {sc.get("scenario_id"): sc for sc in canonical}
    for sc in canonical:
        prov = sc.get("provenance") or {}
        # provenance traceable to a source origin
        if not prov.get("source_file"):
            fail("behavioral.untraceable_provenance", "scenario provenance lacks source_file", sc.get("scenario_id"))
            continue
        # deterministic id: recompute from stable attributes and compare
        recomputed = scenario_id(
            prov.get("source_file", ""),
            str(prov.get("locator", "")),
            prov.get("session_id"),
            prov.get("turn_id"),
            sc.get("raw_prompt", ""),
        )
        # only enforce when the id was generated (not a preserved source id)
        if sc.get("scenario_id", "").startswith("scn_") and sc["scenario_id"] != recomputed:
            fail("behavioral.nondeterministic_id", f"id {sc['scenario_id']} != recomputed {recomputed}", sc.get("scenario_id"))

    # each view record maps to exactly one canonical; views do not duplicate full canonical
    for name, rows in views.items():
        seen: set[str] = set()
        for row in rows:
            sid = row.get("scenario_id")
            if sid in seen:
                fail("behavioral.view_not_unique", f"{name} has duplicate record for {sid}", sid)
            seen.add(sid)
            # a view row must be a thin projection, not the full canonical record
            if set(row.keys()) >= set(REQUIRED_SCENARIO_FIELDS):
                fail("behavioral.view_duplicates_canonical", f"{name} row duplicates canonical for {sid}", sid)
            # tool order preserved when tool data present
            if name == "tool_invocation_eval":
                canon_trace = (by_id.get(sid) or {}).get("trace") or {}
                if row.get("tool_invocation_order") != canon_trace.get("tool_invocation_order"):
                    fail("behavioral.tool_order_lost", f"tool order not preserved for {sid}", sid)

    # ground truth separate from canonical (no raw_prompt leaking into mappings)
    for gt in ground_truth:
        if "raw_prompt" in gt:
            fail("behavioral.gt_not_separate", "ground-truth mapping contains raw_prompt", gt.get("scenario_id"))

    # empty views correctly labeled not-applicable; bootstrap fabrication guard
    if manifest is not None:
        mode = manifest.get("mode")
        for name in VIEW_FILES:
            entry = manifest.get("view_applicability", {}).get(name, {})
            if len(views[name]) == 0 and entry.get("applicable") is not False:
                fail("behavioral.empty_view_mislabeled", f"{name} empty but not marked not-applicable")
            if len(views[name]) == 0 and not entry.get("reason"):
                fail("behavioral.empty_view_no_reason", f"{name} empty but no reason recorded")
        if mode == "bootstrap":
            for name in ("retrieval_eval", "tool_invocation_eval"):
                if views[name]:
                    fail("behavioral.bootstrap_fabrication", f"bootstrap mode produced {name} records")

    return (len(errors) == 0, errors)


def write_validation_artifacts(out_dir: str, passed: bool, errors: list[dict[str, Any]]) -> None:
    vdir = os.path.join(out_dir, "validation")
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, "validation_report.json"), "w", encoding="utf-8") as f:
        json.dump({"status": "passed" if passed else "failed", "error_count": len(errors), "errors": errors}, f, indent=2)
    with open(os.path.join(vdir, "schema_errors.jsonl"), "w", encoding="utf-8") as f:
        for err in errors:
            f.write(json.dumps(err, ensure_ascii=False, sort_keys=True) + "\n")


def _self_test_broken(workdir: str) -> int:
    """Build a deliberately corrupt package and confirm the validator REJECTS it.

    Exit 0 iff validation correctly failed (revision 2). Exit 1 means the validator wrongly
    approved bad input.
    """
    import shutil

    shutil.rmtree(workdir, ignore_errors=True)
    for sub in ("canonical", "ground_truth", "views", "validation", "provenance"):
        os.makedirs(os.path.join(workdir, sub), exist_ok=True)
    # one valid canonical scenario...
    good = {f: None for f in REQUIRED_SCENARIO_FIELDS}
    good.update({"scenario_id": "scn_real", "raw_prompt": "hi", "provenance": {"source_file": "x", "locator": "1"}, "metadata": {}, "trace": None})
    with open(os.path.join(workdir, "canonical", "scenarios.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(good) + "\n")
    # ...but a retrieval view referencing a scenario that does not exist (the injected defect)
    with open(os.path.join(workdir, "views", "retrieval_eval.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"scenario_id": "scn_missing", "retrieved_ids": ["d1"]}) + "\n")
    for name in ("tool_invocation_eval", "response_eval", "end_to_end_eval"):
        open(os.path.join(workdir, "views", f"{name}.jsonl"), "w").close()
    open(os.path.join(workdir, "ground_truth", "mappings.jsonl"), "w").close()
    open(os.path.join(workdir, "provenance", "source_index.jsonl"), "w").close()
    with open(os.path.join(workdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"mode": "full_dataset", "counts": {}, "view_applicability": {}}, f)

    passed, _errors = validate_package(workdir)
    if passed:
        print("SELF-TEST FAILED: validator approved a corrupt package")
        return 1
    print("OK: validator correctly rejected the corrupt package")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate an eval-corpus-forge package (§7).")
    ap.add_argument("--out", help="package directory to validate")
    ap.add_argument("--self-test-broken", dest="broken", help="build a corrupt package here and assert it is rejected")
    args = ap.parse_args()
    if args.broken:
        return _self_test_broken(args.broken)
    if not args.out:
        ap.error("either --out or --self-test-broken is required")
    passed, errors = validate_package(args.out)
    write_validation_artifacts(args.out, passed, errors)
    if not passed:
        print(f"PACKAGE VALIDATION FAILED ({len(errors)} errors):")
        for err in errors[:20]:
            print(f"  - {err['check']}: {err['detail']}")
        return 1
    print("OK: package validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
