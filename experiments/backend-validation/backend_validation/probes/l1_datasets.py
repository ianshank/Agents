"""L1 probe: dataset management — create, insert, fetch, link an item to a run/trace."""

from __future__ import annotations

from backend_validation.registry import register
from backend_validation.runner import ProbeRun

_ITEM_COUNT = 2


@register("l1.datasets.crud_link")
def dataset_crud_link(run: ProbeRun) -> None:
    name = f"bv-dataset-{run.ctx.run_marker}"
    trace = run.op("create_trace", {"name": f"bv-ds-trace-{run.ctx.run_marker}"})
    run.op("create_dataset", {"name": name})
    run.op("insert_dataset_items", {"name": name, "count": _ITEM_COUNT})
    fetched = run.op("fetch_dataset", {"name": name})
    fetched.note(item_count_matches=fetched.ok and f"items={_ITEM_COUNT}" in fetched.outcome.response_excerpt)
    run.op(
        "link_dataset_run",
        {
            "name": name,
            "run_name": f"bv-run-{run.ctx.run_marker}",
            "item_id": fetched.first_artifact(),
            "trace_id": trace.first_artifact(),
        },
    )
