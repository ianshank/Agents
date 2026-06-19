#!/usr/bin/env python3
"""eval-corpus-forge entrypoint: normalize raw eval material into a validated package.

    python scripts/run_eval_corpus_forge.py --in <input> --out <output>

Pipeline (§5): ingest -> normalize -> ground-truth -> views -> manifest -> validate -> swap.
On any precondition failure, stops and reports without fabricating data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forge import ground_truth, ingest, normalize, views
from forge import manifest as manifest_mod
from forge.atomic import commit, make_temp_dir, write_package
from forge.package_validate import validate_package, write_validation_artifacts


def main() -> int:
    ap = argparse.ArgumentParser(description="Forge a validated eval dataset package.")
    ap.add_argument("--in", dest="input", required=True, help="source input file or folder")
    ap.add_argument("--out", required=True, help="output package directory")
    ap.add_argument("--dataset-name", default=None, help="dataset name for the manifest")
    args = ap.parse_args()

    # Step 1: ingest + precondition checks (§1).
    try:
        records = ingest.load_records(args.input)
        ingest.require_prompts(records)
    except ingest.IngestError as e:
        print(f"Precondition failed: {e}", file=sys.stderr)
        return 1
    mode = ingest.detect_mode(records)

    # Steps 2-5: normalize into canonical scenarios.
    canonicals = normalize.normalize_all(records)
    # Step 6: ground truth.
    gt = ground_truth.build_all(canonicals)
    # Step 7: derived views.
    view_data = views.build_views(canonicals)
    provenance = [c["provenance"] for c in canonicals]

    dataset_name = args.dataset_name or os.path.basename(os.path.abspath(args.input.rstrip("/"))) or "dataset"

    # Step 8: atomic write to a sibling temp dir, validate, then swap.
    tmp = make_temp_dir(args.out)
    write_package(tmp, canonicals=canonicals, ground_truth=gt, views=view_data, provenance=provenance)

    manifest = manifest_mod.build_manifest(
        dataset_name=dataset_name,
        source_input=os.path.abspath(args.input),
        mode=mode,
        canonical_count=len(canonicals),
        ground_truth_count=len(gt),
        views=view_data,
        validation_status="pending",
    )
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    passed, errors = validate_package(tmp)
    manifest["validation"]["status"] = "passed" if passed else "failed"
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    write_validation_artifacts(tmp, passed, errors)

    if not passed:
        print("Validation FAILED. Original output left untouched; temp preserved for debugging.", file=sys.stderr)
        print(f"Temp package: {tmp}", file=sys.stderr)
        print(f"Report: {os.path.join(tmp, 'validation', 'validation_report.json')}", file=sys.stderr)
        for err in errors[:20]:
            print(f"  - {err['check']}: {err['detail']}", file=sys.stderr)
        return 1

    commit(tmp, args.out)
    counts = manifest["counts"]
    print("Dataset package created and validated.\n")
    print(f"Output: {args.out}")
    print(f"Manifest: {os.path.join(args.out, 'manifest.json')}")
    print(f"Canonical scenarios: {counts['canonical_scenarios']}")
    print(f"Ground-truth mappings: {counts['ground_truth_mappings']}")
    print(f"Retrieval eval records: {counts['retrieval_eval_records']}")
    print(f"Tool invocation eval records: {counts['tool_invocation_eval_records']}")
    print(f"Response eval records: {counts['response_eval_records']}")
    print(f"End-to-end eval records: {counts['end_to_end_eval_records']}")
    print("Validation: passed")
    print(f"Evidence: {os.path.join(args.out, 'validation', 'validation_report.json')}")

    na = [(n, v["reason"]) for n, v in view_data.items() if not v["applicable"]]
    if na:
        print("\nNot applicable views:")
        for name, reason in na:
            print(f"- {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
