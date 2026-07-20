"""L1 probes: CI/regression two-run comparison and experiment diffing.

``nonzero_exit_available`` is a DERIVED observable, by explicit rule: a structured
(machine-readable) comparison payload is exactly what lets a CI script exit non-zero on
regression. The derivation is visible here and echoed in the report — no hidden judgment.
"""

from __future__ import annotations

from backend_validation.probes import structured
from backend_validation.registry import register
from backend_validation.runner import ProbeRun


@register("l1.ci.two_run_compare")
def two_run_compare(run: ProbeRun) -> None:
    name = f"bv-ci-{run.ctx.run_marker}"
    run.op("create_dataset", {"name": name})
    run.op("insert_dataset_items", {"name": name, "count": 2})
    fetched = run.op("fetch_dataset", {"name": name})
    for suffix in ("r1", "r2"):
        trace = run.op("create_trace", {"name": f"bv-ci-trace-{suffix}-{run.ctx.run_marker}"})
        run.op(
            "create_experiment_run",
            {
                "name": name,
                "run_name": f"bv-{suffix}-{run.ctx.run_marker}",
                "item_id": fetched.first_artifact(),
                "trace_id": trace.first_artifact(),
            },
        )
    compared = run.op("compare_runs", {"name": name})
    machine_readable = compared.ok and structured(compared.outcome.response_excerpt)
    compared.note(machine_readable=machine_readable)
    compared.note(nonzero_exit_available=machine_readable)  # derived; see module docstring


@register("l1.compare.diff_runs")
def diff_runs(run: ProbeRun) -> None:
    name = f"bv-diff-{run.ctx.run_marker}"
    run.op("create_dataset", {"name": name})
    diffed = run.op("diff_runs", {"name": name})
    diffed.note(diff_machine_readable=diffed.ok and structured(diffed.outcome.response_excerpt))
