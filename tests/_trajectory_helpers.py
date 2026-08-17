"""Shared builders for trajectory tests.

Kept out of the test modules themselves so the contract suite and the scorer suite
construct trajectories the same way, and a change to the step shape updates one place.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from eval_harness.core.types import (
    AgentTrajectory,
    EvalItem,
    ItemResult,
    RunResult,
    TargetOutput,
    ToolCallRecord,
    TrajectoryStep,
)


def call(name: str, arguments: dict[str, Any] | None = None, call_id: str | None = None) -> ToolCallRecord:
    return ToolCallRecord(name=name, arguments=arguments or {}, call_id=call_id)


def tool_call(name: str, arguments: dict[str, Any] | None = None) -> TrajectoryStep:
    return TrajectoryStep(kind="tool_call", tool_call=call(name, arguments))


def observation(content: Any, name: str | None = None) -> TrajectoryStep:
    return TrajectoryStep(
        kind="tool_observation",
        tool_call=call(name) if name else None,
        content=content,
    )


def tool_error(name: str, content: Any = "boom") -> TrajectoryStep:
    return TrajectoryStep(kind="tool_error", tool_call=call(name), content=content)


def final(content: Any = "done", failed: bool = False) -> TrajectoryStep:
    """A terminal step. ``failed=True`` marks it as *not* claiming success."""
    return TrajectoryStep(kind="final", content=content, metadata={"failed": True} if failed else {})


def trajectory(*steps: TrajectoryStep) -> AgentTrajectory:
    return AgentTrajectory(steps=tuple(steps))


def output_with(*steps: TrajectoryStep, output: Any = "answer") -> TargetOutput:
    return TargetOutput(output=output, trajectory=trajectory(*steps))


def item(expected: Any = None, **metadata: Any) -> EvalItem:
    return EvalItem(id="i", inputs={}, expected=expected, metadata=metadata)


def run_result(target_output: TargetOutput) -> RunResult:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    return RunResult(
        run_id="r",
        config_name="c",
        items=[ItemResult(item=EvalItem(id="i", inputs={}), output=target_output)],
        aggregate={},
        started_at=moment,
        finished_at=moment,
    )
