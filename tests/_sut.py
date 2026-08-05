"""A trivial system-under-test for exercising the dynamic CallableTarget."""

from __future__ import annotations


def summarize(inputs: dict) -> str:
    return f"summary: {inputs.get('text', '')}"


def boom(inputs: dict) -> str:
    raise ValueError("kaboom")


def echo_item(item: object) -> str:
    """Receives the whole EvalItem (used to exercise CallableTarget(pass_item=True))."""
    return f"item: {getattr(item, 'id', '?')}"


def trajectory_demo(inputs: dict):
    """A tool-using SUT that returns a full ``TargetOutput`` including a trajectory.

    Exercises ``CallableTarget``'s TargetOutput pass-through, which is what makes F-051
    reachable from a YAML config without writing a bespoke ``TargetRunner``. Deterministic:
    the same inputs always produce the same trajectory.
    """
    from eval_harness.core.types import AgentTrajectory, TargetOutput, ToolCallRecord, TrajectoryStep

    question = inputs.get("question", "")
    trajectory = AgentTrajectory(
        steps=(
            TrajectoryStep(kind="model_decision", content="need a lookup"),
            TrajectoryStep(kind="tool_call", tool_call=ToolCallRecord("search", {"q": question})),
            TrajectoryStep(kind="tool_observation", content="1 result"),
            TrajectoryStep(kind="tool_call", tool_call=ToolCallRecord("fetch", {"id": "42"})),
            TrajectoryStep(kind="tool_observation", content="widget 42 is blue"),
            TrajectoryStep(kind="final", content="Widget 42 is blue."),
        )
    )
    return TargetOutput(output="Widget 42 is blue.", trajectory=trajectory)


def preset_latency_output(inputs: dict):
    """Returns a TargetOutput that already carries its own latency measurement."""
    from eval_harness.core.types import TargetOutput

    return TargetOutput(output="preset", latency_ms=123.5)
