"""Replay envelope: a versioned wrapper around a recorded ``AgentTrajectory``.

The envelope schema version is independent of config ``SCHEMA_VERSION`` and of
``TRAJECTORY_SCHEMA_VERSION`` (ADR 0049). Parsing is strict: unknown keys raise.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from ..core.types import (
    TRAJECTORY_SCHEMA_VERSION,
    AgentTrajectory,
    StateSnapshot,
    ToolCallRecord,
    TrajectoryStep,
    trajectory_to_dict,
)

#: Envelope payload shape. Independent of config schema and of trajectory schema.
ENVELOPE_SCHEMA_VERSION = "1.0.0"

ReplayMode = Literal["exact", "counterfactual"]


class ReplayError(ValueError):
    """Raised when an envelope, trajectory payload, or replay config is invalid."""


def canonical_hash(value: Any) -> str:
    """Stable SHA-256 of JSON-canonical *value* (sorted keys, no ``id()``)."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _freeze_str_map(mapping: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(mapping))


def _freeze_any_map(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


def _reject_unknown(raw: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    extra = set(raw) - allowed
    if extra:
        raise ReplayError(f"{label} has unknown keys: {sorted(extra)}")


_TRAJECTORY_KEYS = frozenset({"schema_version", "steps"})
_STEP_KEYS = frozenset({"kind", "timestamp_ms", "tool_call", "content", "metadata"})
_CALL_KEYS = frozenset({"name", "arguments", "call_id"})
_STEP_KINDS: frozenset[str] = frozenset({"model_decision", "tool_call", "tool_observation", "tool_error", "final"})


def _tool_call_from_dict(raw: object) -> ToolCallRecord:
    if not isinstance(raw, dict):
        raise ReplayError(f"tool_call must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, _CALL_KEYS, "tool_call")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ReplayError("tool_call.name must be a non-empty string")
    arguments = raw.get("arguments", {})
    if not isinstance(arguments, Mapping):
        raise ReplayError("tool_call.arguments must be a mapping")
    call_id = raw.get("call_id")
    if call_id is not None and not isinstance(call_id, str):
        raise ReplayError("tool_call.call_id must be a string when present")
    return ToolCallRecord(name=name, arguments=dict(arguments), call_id=call_id)


def _step_from_dict(raw: object) -> TrajectoryStep:
    if not isinstance(raw, dict):
        raise ReplayError(f"trajectory step must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, _STEP_KEYS, "trajectory step")
    kind = raw.get("kind")
    if kind not in _STEP_KINDS:
        raise ReplayError(f"unknown step kind: {kind!r}")
    timestamp_ms = raw.get("timestamp_ms")
    if timestamp_ms is not None and not isinstance(timestamp_ms, int):
        raise ReplayError("timestamp_ms must be an int when present")
    tool_call_raw = raw.get("tool_call")
    tool_call = _tool_call_from_dict(tool_call_raw) if tool_call_raw is not None else None
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ReplayError("step metadata must be a mapping")
    return TrajectoryStep(
        kind=kind,
        timestamp_ms=timestamp_ms,
        tool_call=tool_call,
        content=raw.get("content"),
        metadata=dict(metadata),
    )


def trajectory_from_dict(raw: object) -> AgentTrajectory:
    """Inverse of :func:`trajectory_to_dict`. Unknown keys raise :class:`ReplayError`."""
    if not isinstance(raw, dict):
        raise ReplayError(f"trajectory payload must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, _TRAJECTORY_KEYS, "trajectory")
    version = raw.get("schema_version", TRAJECTORY_SCHEMA_VERSION)
    if version != TRAJECTORY_SCHEMA_VERSION:
        raise ReplayError(f"unsupported trajectory schema_version: {version!r}")
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list):
        raise ReplayError("trajectory.steps must be a list")
    steps = tuple(_step_from_dict(step) for step in steps_raw)
    return AgentTrajectory(steps=steps, schema_version=TRAJECTORY_SCHEMA_VERSION)


def state_snapshot_from_dict(raw: object) -> StateSnapshot | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ReplayError(f"state snapshot must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, frozenset({"data"}), "state snapshot")
    data = raw.get("data", {})
    if not isinstance(data, Mapping):
        raise ReplayError("state snapshot data must be a mapping")
    return StateSnapshot(data=dict(data))


def state_snapshot_to_dict(snapshot: StateSnapshot) -> dict[str, Any]:
    return {"data": dict(snapshot.data)}


_ENVELOPE_KEYS = frozenset(
    {
        "envelope_id",
        "recorded_run_id",
        "item_id",
        "recorded_at",
        "environment",
        "agent_version",
        "prompt_version",
        "model_id",
        "model_parameters_hash",
        "dependency_snapshot_id",
        "input_hash",
        "output_hash",
        "trajectory",
        "state_before",
        "state_after",
        "tags",
        "payload_refs",
        "output",
        "output_metadata",
        "schema_version",
    }
)


def _str_map(raw: object, label: str) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise ReplayError(f"{label} must be a mapping")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ReplayError(f"{label} keys and values must be strings")
        out[key] = value
    return out


@dataclass(frozen=True)
class ReplayConfig:
    """Operator-facing defaults for fixture replay. Numeric/string knobs live here."""

    mode: ReplayMode = "exact"
    archive_path: str = ""
    from_span: str | None = None
    override_tag_key: str = "freshness"
    override_tag_value: str = ""
    missing_envelope_error: str = "no recorded envelope for item"
    error_override_prefix: str = "error:"
    override_key_prefix: str = "tool."
    default_environment: str = "offline"
    default_agent_version: str = "unknown"
    pass_rate_digits: int = 2
    slice_score: str = "trajectory_recovery"
    default_scorers: tuple[str, ...] = ("trajectory_in_order", "trajectory_recovery")
    html_title: str = "Fixture replay"
    allowed_modes: tuple[str, ...] = ("exact", "counterfactual")

    def __post_init__(self) -> None:
        if self.mode not in self.allowed_modes:
            raise ReplayError(f"invalid replay mode: {self.mode!r}")
        if self.pass_rate_digits < 0:
            raise ReplayError("pass_rate_digits must be >= 0")


@dataclass(frozen=True)
class ReplayEnvelope:
    """Recorded execution evidence for one eval item. Target-owned; never from spans."""

    envelope_id: str
    recorded_run_id: str
    item_id: str
    recorded_at: str
    environment: str
    agent_version: str
    input_hash: str
    output_hash: str
    trajectory: AgentTrajectory
    prompt_version: str | None = None
    model_id: str | None = None
    model_parameters_hash: str | None = None
    dependency_snapshot_id: str | None = None
    state_before: StateSnapshot | None = None
    state_after: StateSnapshot | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    payload_refs: Mapping[str, str] = field(default_factory=dict)
    output: Any = None
    output_metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _freeze_str_map(self.tags))
        object.__setattr__(self, "payload_refs", _freeze_str_map(self.payload_refs))
        object.__setattr__(self, "output_metadata", _freeze_any_map(self.output_metadata))
        if self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise ReplayError(f"unsupported envelope schema_version: {self.schema_version!r}")


def envelope_to_dict(envelope: ReplayEnvelope) -> dict[str, Any]:
    """JSON-ready envelope. Empty optional mappings and Nones are omitted."""
    payload: dict[str, Any] = {
        "schema_version": envelope.schema_version,
        "envelope_id": envelope.envelope_id,
        "recorded_run_id": envelope.recorded_run_id,
        "item_id": envelope.item_id,
        "recorded_at": envelope.recorded_at,
        "environment": envelope.environment,
        "agent_version": envelope.agent_version,
        "input_hash": envelope.input_hash,
        "output_hash": envelope.output_hash,
        "trajectory": trajectory_to_dict(envelope.trajectory),
    }
    if envelope.prompt_version is not None:
        payload["prompt_version"] = envelope.prompt_version
    if envelope.model_id is not None:
        payload["model_id"] = envelope.model_id
    if envelope.model_parameters_hash is not None:
        payload["model_parameters_hash"] = envelope.model_parameters_hash
    if envelope.dependency_snapshot_id is not None:
        payload["dependency_snapshot_id"] = envelope.dependency_snapshot_id
    if envelope.state_before is not None:
        payload["state_before"] = state_snapshot_to_dict(envelope.state_before)
    if envelope.state_after is not None:
        payload["state_after"] = state_snapshot_to_dict(envelope.state_after)
    if envelope.tags:
        payload["tags"] = dict(envelope.tags)
    if envelope.payload_refs:
        payload["payload_refs"] = dict(envelope.payload_refs)
    if envelope.output is not None:
        payload["output"] = envelope.output
    if envelope.output_metadata:
        payload["output_metadata"] = dict(envelope.output_metadata)
    return payload


def envelope_from_dict(raw: object) -> ReplayEnvelope:
    """Parse one envelope. Unknown keys raise :class:`ReplayError`."""
    if not isinstance(raw, dict):
        raise ReplayError(f"envelope must be a mapping, got {type(raw).__name__}")
    _reject_unknown(raw, _ENVELOPE_KEYS, "envelope")
    version = raw.get("schema_version", ENVELOPE_SCHEMA_VERSION)
    if version != ENVELOPE_SCHEMA_VERSION:
        raise ReplayError(f"unsupported envelope schema_version: {version!r}")
    required = (
        "envelope_id",
        "recorded_run_id",
        "item_id",
        "recorded_at",
        "environment",
        "agent_version",
        "input_hash",
        "output_hash",
        "trajectory",
    )
    for key in required:
        if key not in raw:
            raise ReplayError(f"envelope missing required key: {key}")
        if key != "trajectory" and not isinstance(raw[key], str):
            raise ReplayError(f"envelope.{key} must be a string")
    metadata_raw = raw.get("output_metadata", {})
    if not isinstance(metadata_raw, Mapping):
        raise ReplayError("output_metadata must be a mapping")
    return ReplayEnvelope(
        envelope_id=str(raw["envelope_id"]),
        recorded_run_id=str(raw["recorded_run_id"]),
        item_id=str(raw["item_id"]),
        recorded_at=str(raw["recorded_at"]),
        environment=str(raw["environment"]),
        agent_version=str(raw["agent_version"]),
        input_hash=str(raw["input_hash"]),
        output_hash=str(raw["output_hash"]),
        trajectory=trajectory_from_dict(raw["trajectory"]),
        prompt_version=raw.get("prompt_version"),
        model_id=raw.get("model_id"),
        model_parameters_hash=raw.get("model_parameters_hash"),
        dependency_snapshot_id=raw.get("dependency_snapshot_id"),
        state_before=state_snapshot_from_dict(raw.get("state_before")),
        state_after=state_snapshot_from_dict(raw.get("state_after")),
        tags=_str_map(raw.get("tags", {}), "tags"),
        payload_refs=_str_map(raw.get("payload_refs", {}), "payload_refs"),
        output=raw.get("output"),
        output_metadata=dict(metadata_raw),
        schema_version=ENVELOPE_SCHEMA_VERSION,
    )
