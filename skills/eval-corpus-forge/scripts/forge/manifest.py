"""§6 manifest. Counts are the in-memory tally of records the pipeline wrote.

package_validate re-counts from disk and compares, so a mismatch surfaces a dropped or
truncated write (revision 3 — the check is meaningful, not tautological).
"""
from __future__ import annotations

import datetime
from typing import Any

SCHEMA_VERSION = "1.0.0"


def build_manifest(
    *,
    dataset_name: str,
    source_input: str,
    mode: str,
    canonical_count: int,
    ground_truth_count: int,
    views: dict[str, dict[str, Any]],
    validation_status: str,
) -> dict[str, Any]:
    counts = {
        "canonical_scenarios": canonical_count,
        "ground_truth_mappings": ground_truth_count,
        "retrieval_eval_records": len(views["retrieval_eval"]["records"]),
        "tool_invocation_eval_records": len(views["tool_invocation_eval"]["records"]),
        "response_eval_records": len(views["response_eval"]["records"]),
        "end_to_end_eval_records": len(views["end_to_end_eval"]["records"]),
    }
    view_applicability = {
        name: {"applicable": views[name]["applicable"], "reason": views[name]["reason"]}
        for name in views
    }
    return {
        "dataset_name": dataset_name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_input": source_input,
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "counts": counts,
        "view_applicability": view_applicability,
        "validation": {
            "status": validation_status,
            "report_path": "validation/validation_report.json",
        },
    }
