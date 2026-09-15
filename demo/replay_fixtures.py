"""Deterministic demo envelopes for fixture replay (beat 6).

Used by tests and by ``python demo/replay_fixtures.py`` to emit
``demo/replay/baseline.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval_harness.core.types import AgentTrajectory, ToolCallRecord, TrajectoryStep
from eval_harness.replay.envelope import ReplayEnvelope, canonical_hash, envelope_to_dict

_REPO = Path(__file__).resolve().parent
_OUT = _REPO / "replay" / "baseline.jsonl"
_ITEM_COUNT = 12
_SENSITIVE_EVERY = 3
_RECORDED_AT = "2026-09-14T00:00:00+00:00"


def _search_hit(*, stale: bool) -> str:
    if stale:
        return "STALE: Q3 travel policy superseded 2025-01-01"
    return "FRESH: current travel policy effective 2026-09-01"


def _steps(*, stale: bool) -> tuple[TrajectoryStep, ...]:
    search = ToolCallRecord(name="search", arguments={"q": "travel policy"})
    fetch = ToolCallRecord(name="fetch", arguments={"url": "https://example.invalid/policy"})
    return (
        TrajectoryStep(kind="model_decision", content="look up policy"),
        TrajectoryStep(kind="tool_call", tool_call=search, metadata={"span_id": "search"}),
        TrajectoryStep(kind="tool_observation", tool_call=search, content=_search_hit(stale=stale)),
        TrajectoryStep(kind="tool_call", tool_call=fetch, metadata={"span_id": "fetch"}),
        TrajectoryStep(kind="tool_observation", tool_call=fetch, content="policy body"),
        TrajectoryStep(kind="final", content="here is the current policy"),
    )


def is_sensitive(index: int) -> bool:
    return index % _SENSITIVE_EVERY == 0


def build_envelope(index: int, *, stale: bool = False) -> ReplayEnvelope:
    item_id = f"replay-{index:02d}"
    freshness = "sensitive" if is_sensitive(index) else "normal"
    trajectory = AgentTrajectory(steps=_steps(stale=stale))
    output = {"answer": "current travel policy", "requirements": []}
    return ReplayEnvelope(
        envelope_id=f"env-{item_id}",
        recorded_run_id="demo-replay-baseline",
        item_id=item_id,
        recorded_at=_RECORDED_AT,
        environment="offline-demo",
        agent_version="demo-1",
        input_hash=canonical_hash({"id": item_id}),
        output_hash=canonical_hash(output),
        trajectory=trajectory,
        output=output,
        tags={"freshness": freshness},
    )


def build_baseline() -> tuple[ReplayEnvelope, ...]:
    return tuple(build_envelope(index, stale=False) for index in range(_ITEM_COUNT))


def write_baseline(path: Path | None = None) -> Path:
    target = path if path is not None else _OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(envelope_to_dict(env), sort_keys=True) for env in build_baseline()]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    written = write_baseline()
    print(written)
