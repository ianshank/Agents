"""Registered ``replay`` TargetRunner: exact re-score or counterfactual observation swap.

``run`` takes only the item (REVIEW.md §B14). Mode, archive, and overrides live on
the constructor — YAML ``target.params`` or the CLI. Counterfactual is this target,
never a scorer (ADR 0046 / ADR 0049).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast

from ..core._imports import import_allowed_module, resolve_allowed_attribute
from ..core.interfaces import TargetRunner
from ..core.types import AgentTrajectory, EvalItem, TargetOutput, TrajectoryStep
from ..plugins import TARGETS
from .archive import ReplayArchive
from .envelope import ReplayConfig, ReplayEnvelope, ReplayError, ReplayMode

logger = logging.getLogger(__name__)


def _looks_like_callable_path(value: str) -> bool:
    """Dotted ``module.attr:name`` paths only — ``error:stale`` is a literal prefix."""
    if ":" not in value:
        return False
    module, _, attr = value.partition(":")
    return "." in module and bool(attr) and attr.isidentifier()


def _resolve_override(value: str, recorded: Any) -> str:
    if not _looks_like_callable_path(value):
        return value
    module_name, _, attr = value.partition(":")
    module = import_allowed_module(module_name)
    fn = resolve_allowed_attribute(module, attr)
    if not callable(fn):
        raise ReplayError(f"override target {value!r} is not callable")
    result = fn(recorded)
    return result if isinstance(result, str) else str(result)


def _span_index(trajectory: AgentTrajectory, from_span: str | None) -> int:
    """Index at which overrides may start. ``None`` means the whole trajectory."""
    if from_span is None or from_span == "":
        return 0
    if from_span.isdigit():
        return int(from_span)
    for index, step in enumerate(trajectory.steps):
        span_id = step.metadata.get("span_id")
        if span_id == from_span:
            return index
        if step.tool_call is not None and step.tool_call.name == from_span:
            return index
    raise ReplayError(f"from_span {from_span!r} did not match a recorded step")


def apply_counterfactual(
    trajectory: AgentTrajectory,
    overrides: Mapping[str, str],
    *,
    from_span: str | None = None,
    error_prefix: str | None = None,
    config: ReplayConfig | None = None,
) -> AgentTrajectory:
    """Pin recorded steps; replace matching tool observations after *from_span*."""
    cfg = config or ReplayConfig()
    prefix = cfg.error_override_prefix if error_prefix is None else error_prefix
    start = _span_index(trajectory, from_span)
    rebuilt: list[TrajectoryStep] = []
    for index, step in enumerate(trajectory.steps):
        if index < start or step.tool_call is None:
            rebuilt.append(step)
            continue
        if step.kind not in ("tool_observation", "tool_error"):
            rebuilt.append(step)
            continue
        replacement = overrides.get(step.tool_call.name)
        if replacement is None:
            rebuilt.append(step)
            continue
        resolved = _resolve_override(replacement, step.content)
        if resolved.startswith(prefix):
            rebuilt.append(
                TrajectoryStep(
                    kind="tool_error",
                    timestamp_ms=step.timestamp_ms,
                    tool_call=step.tool_call,
                    content=resolved[len(prefix) :],
                    metadata=dict(step.metadata),
                )
            )
            continue
        rebuilt.append(
            TrajectoryStep(
                kind="tool_observation",
                timestamp_ms=step.timestamp_ms,
                tool_call=step.tool_call,
                content=resolved,
                metadata=dict(step.metadata),
            )
        )
    return AgentTrajectory(steps=tuple(rebuilt), schema_version=trajectory.schema_version)


def _normalize_overrides(raw: Mapping[str, str] | None, prefix: str) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = key[len(prefix) :] if key.startswith(prefix) else key
        if not name:
            raise ReplayError("override tool name is empty")
        out[name] = value
    return out


@TARGETS.register("replay")
class ReplayTarget(TargetRunner):
    """Reload a recorded envelope and emit it as ``TargetOutput``.

    Missing envelopes degrade to a scored error (ADR 0038), not a crash.
    Invalid mode / corrupt archive fail closed at construction or first load.
    """

    def __init__(
        self,
        archive: str = "",
        mode: str = "exact",
        overrides: Mapping[str, str] | None = None,
        from_span: str | None = None,
        override_tag_key: str | None = None,
        override_tag_value: str | None = None,
        envelopes: Sequence[ReplayEnvelope] | None = None,
        config: ReplayConfig | None = None,
    ) -> None:
        base = config or ReplayConfig()
        if mode not in base.allowed_modes:
            raise ReplayError(f"invalid replay mode: {mode!r}")
        self.config = replace(
            base,
            mode=cast(ReplayMode, mode),
            archive_path=archive if archive else base.archive_path,
            from_span=from_span if from_span is not None else base.from_span,
            override_tag_key=override_tag_key if override_tag_key is not None else base.override_tag_key,
            override_tag_value=override_tag_value if override_tag_value is not None else base.override_tag_value,
        )
        self._overrides = _normalize_overrides(overrides, self.config.override_key_prefix)
        self._injected = tuple(envelopes) if envelopes is not None else None
        self._index: dict[str, ReplayEnvelope] | None = None

    def is_deterministic(self) -> bool:
        return True

    def _load_index(self) -> dict[str, ReplayEnvelope]:
        if self._index is not None:
            return self._index
        if self._injected is not None:
            self._index = {env.item_id: env for env in self._injected}
            return self._index
        path = self.config.archive_path
        if not path:
            raise ReplayError("replay target requires archive= or injected envelopes")
        self._index = dict(ReplayArchive(path).by_item_id())
        return self._index

    def _should_override(self, envelope: ReplayEnvelope) -> bool:
        wanted = self.config.override_tag_value
        if not wanted:
            return True
        return envelope.tags.get(self.config.override_tag_key) == wanted

    def run(self, item: EvalItem) -> TargetOutput:
        try:
            index = self._load_index()
        except ReplayError as exc:
            logger.debug("replay archive failed closed for item %s: %s", item.id, exc)
            return TargetOutput(output=None, error=str(exc))
        envelope = index.get(item.id)
        if envelope is None:
            return TargetOutput(output=None, error=self.config.missing_envelope_error)
        trajectory = envelope.trajectory
        mode: ReplayMode = self.config.mode
        if mode == "counterfactual" and self._overrides and self._should_override(envelope):
            try:
                trajectory = apply_counterfactual(
                    trajectory,
                    self._overrides,
                    from_span=self.config.from_span,
                    config=self.config,
                )
            except ReplayError as exc:
                return TargetOutput(output=None, error=str(exc), trajectory=envelope.trajectory)
        metadata = dict(envelope.output_metadata)
        metadata["replay_envelope_id"] = envelope.envelope_id
        metadata["replay_mode"] = mode
        return TargetOutput(
            output=envelope.output,
            metadata=metadata,
            trajectory=trajectory,
        )
