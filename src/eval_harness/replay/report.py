"""First failing step and a small HTML/text renderer for fixture replay."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import Any

from ..core.types import AgentTrajectory, ItemResult, TrajectoryStep
from .envelope import ReplayConfig
from .slice import SliceRow, global_pass_rate, pass_rates_by_tag


@dataclass(frozen=True)
class FailingStep:
    item_id: str
    index: int
    kind: str
    tool_name: str | None
    content: Any


def _tool_name(step: TrajectoryStep) -> str | None:
    if step.tool_call is None:
        return None
    return step.tool_call.name


def first_failing_step(trajectory: AgentTrajectory, *, item_id: str = "") -> FailingStep | None:
    """Earliest ``tool_error`` step, or ``None`` when the path has no tool error."""
    for index, step in enumerate(trajectory.steps):
        if step.kind == "tool_error":
            return FailingStep(
                item_id=item_id,
                index=index,
                kind=step.kind,
                tool_name=_tool_name(step),
                content=step.content,
            )
    return None


def failing_steps(results: Sequence[ItemResult]) -> tuple[FailingStep, ...]:
    found: list[FailingStep] = []
    for result in results:
        trajectory = result.output.trajectory
        if trajectory is None:
            continue
        step = first_failing_step(trajectory, item_id=result.item.id)
        if step is not None:
            found.append(step)
    return tuple(found)


def format_pass_rate(rate: float | None, *, digits: int | None = None, config: ReplayConfig | None = None) -> str:
    cfg = config or ReplayConfig()
    width = cfg.pass_rate_digits if digits is None else digits
    if rate is None:
        return "n/a"
    return f"{rate:.{width}f}"


def render_text(
    results: Sequence[ItemResult],
    *,
    tag_key: str | None = None,
    config: ReplayConfig | None = None,
) -> str:
    """CLI-facing summary: global pass-rate, optional slice, first failing steps."""
    cfg = config or ReplayConfig()
    passed, n, rate = global_pass_rate(results, config=cfg)
    lines = [
        f"global {cfg.slice_score} pass_rate={format_pass_rate(rate, config=cfg)} passed={passed} n={n}",
    ]
    key = tag_key if tag_key is not None else cfg.override_tag_key
    for row in pass_rates_by_tag(results, key, config=cfg):
        label = row.tag_value if row.tag_value else "(untagged)"
        lines.append(
            f"slice {row.tag_key}={label} pass_rate={format_pass_rate(row.pass_rate, config=cfg)} "
            f"passed={row.passed} n={row.n}"
        )
    steps = failing_steps(results)
    if not steps:
        lines.append("first_failing_step: (none)")
    else:
        lines.append("first_failing_step:")
        for step in steps:
            tool = step.tool_name or "<unknown>"
            lines.append(f"  {step.item_id}: {step.kind} {tool} @ step {step.index}: {step.content}")
    return "\n".join(lines)


def _step_path(trajectory: AgentTrajectory) -> str:
    names: list[str] = []
    for step in trajectory.steps:
        if step.kind == "tool_call" and step.tool_call is not None:
            names.append(step.tool_call.name)
        elif step.kind == "tool_error":
            tool = _tool_name(step) or "tool"
            names.append(f"tool_error({tool})")
        elif step.kind == "final":
            names.append("final")
    return " → ".join(names) if names else "(no tools)"


def render_html(
    results: Sequence[ItemResult],
    *,
    tag_key: str | None = None,
    config: ReplayConfig | None = None,
    title: str | None = None,
) -> str:
    """Self-contained HTML table. Ordered steps, not a vendor waterfall."""
    cfg = config or ReplayConfig()
    heading = title if title is not None else cfg.html_title
    passed, n, rate = global_pass_rate(results, config=cfg)
    key = tag_key if tag_key is not None else cfg.override_tag_key
    slices: Sequence[SliceRow] = pass_rates_by_tag(results, key, config=cfg)
    rows: list[str] = []
    for result in results:
        trajectory = result.output.trajectory
        fail = first_failing_step(trajectory, item_id=result.item.id) if trajectory is not None else None
        tags = result.item.metadata.get("replay_tags") or {}
        fail_cell = ""
        if fail is not None:
            tool = fail.tool_name or "<unknown>"
            fail_cell = f"{escape(str(fail.kind))} {escape(str(tool))} @ {fail.index}: {escape(str(fail.content))}"
        path = _step_path(trajectory) if trajectory is not None else "(no trajectory)"
        rows.append(
            "<tr>"
            f"<td>{escape(result.item.id)}</td>"
            f"<td>{escape(str(tags))}</td>"
            f"<td>{escape(path)}</td>"
            f"<td>{fail_cell or '—'}</td>"
            "</tr>"
        )
    slice_items = "".join(
        f"<li>{escape(row.tag_key)}={escape(row.tag_value or '(untagged)')}: "
        f"pass_rate={escape(format_pass_rate(row.pass_rate, config=cfg))} n={row.n}</li>"
        for row in slices
    )
    body = "\n".join(rows)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{escape(heading)}</title>"
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}</style>"
        f"</head><body><h1>{escape(heading)}</h1>"
        f"<p>global {escape(cfg.slice_score)} pass_rate="
        f"{escape(format_pass_rate(rate, config=cfg))} passed={passed} n={n}</p>"
        f"<ul>{slice_items}</ul>"
        "<table><thead><tr><th>item</th><th>tags</th><th>steps</th>"
        "<th>first tool_error</th></tr></thead>"
        f"<tbody>{body}</tbody></table></body></html>"
    )
