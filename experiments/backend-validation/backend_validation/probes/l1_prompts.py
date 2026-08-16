"""L1 probe: prompt management — create, version, fetch-latest, rollback."""

from __future__ import annotations

from backend_validation.registry import register
from backend_validation.runner import ProbeRun


@register("l1.prompts.version_cycle")
def prompt_version_cycle(run: ProbeRun) -> None:
    name = f"bv-prompt-{run.ctx.run_marker}"
    v2_text = f"v2-{run.ctx.run_marker}"
    run.op("create_prompt", {"name": name, "text": "v1"})
    run.op("create_prompt_version", {"name": name, "text": v2_text})
    fetched = run.op("fetch_prompt", {"name": name})
    fetched.note(fetched_latest_matches=fetched.ok and v2_text[:10] in fetched.outcome.response_excerpt)
    # `version` drives Langfuse's label-move rollback; `text` (the v1 body created above)
    # drives Opik's recreate-as-latest rollback, which must verify the resulting text.
    run.op("rollback_prompt", {"name": name, "version": 1, "text": "v1"})
