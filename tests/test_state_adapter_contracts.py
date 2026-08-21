"""Contract guarantees for the StateAdapter seam: value objects, Protocol shape, wiring.

Group 1 of add-stateful-outcome-evaluation (F-060) — the seam itself, not an
adapter's behavior. The ``in_memory`` adapter's own logic is covered by
``tests/test_matrix_state_adapters.py``; this file tests only what every
future adapter must satisfy structurally.
"""

from __future__ import annotations

import dataclasses

import pytest

from eval_harness.config.models import ComponentSpec, EvalConfig
from eval_harness.core.interfaces import StateAdapter
from eval_harness.core.registry import RegistryError
from eval_harness.core.types import EvalItem, RunContext, StateEvaluation, StateSnapshot
from eval_harness.plugins import STATE_ADAPTERS
from eval_harness.version import SCHEMA_VERSION


def test_state_snapshot_data_is_read_only() -> None:
    snap = StateSnapshot(data={"balance": 100})
    with pytest.raises(TypeError):
        snap.data["balance"] = 0  # type: ignore[index]


def test_state_snapshot_is_frozen() -> None:
    snap = StateSnapshot(data={"a": 1})
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.data = {}  # type: ignore[misc]


def test_state_snapshot_defaults_to_an_empty_mapping() -> None:
    assert StateSnapshot().data == {}


def test_state_evaluation_defaults() -> None:
    ev = StateEvaluation(goal_reached=True)
    assert ev.policy_violated is False
    assert ev.reasoning == ""
    assert ev.metadata == {}


def test_state_evaluation_goal_and_policy_are_independent_axes() -> None:
    """The scenario tasks.md names explicitly: goal reached via a forbidden mutation."""
    ev = StateEvaluation(goal_reached=True, policy_violated=True, reasoning="wrote to a locked path")
    assert ev.goal_reached is True
    assert ev.policy_violated is True


def test_state_evaluation_metadata_is_read_only() -> None:
    ev = StateEvaluation(goal_reached=False, metadata={"k": "v"})
    with pytest.raises(TypeError):
        ev.metadata["k"] = "changed"  # type: ignore[index]


def test_state_adapter_protocol_duck_typing() -> None:
    class DuckAdapter:
        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            return StateSnapshot()

        def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
            return StateEvaluation(goal_reached=True)

        def reset(self, ctx: RunContext) -> None:
            return None

    assert isinstance(DuckAdapter(), StateAdapter)


def test_state_adapter_protocol_rejects_a_partial_shape() -> None:
    class MissingReset:
        def snapshot(self, ctx: RunContext) -> StateSnapshot:
            return StateSnapshot()

        def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
            return StateEvaluation(goal_reached=True)

    assert not isinstance(MissingReset(), StateAdapter)


def test_state_adapters_registry_rejects_an_unregistered_name() -> None:
    with pytest.raises(RegistryError):
        STATE_ADAPTERS.create("does-not-exist", {})


def test_eval_config_accepts_a_state_adapter_component() -> None:
    config = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "state_adapter": {"type": "in_memory", "params": {}},
        }
    )
    assert config.state_adapter == ComponentSpec(type="in_memory", params={})


def test_eval_config_state_adapter_defaults_to_none() -> None:
    config = EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
        }
    )
    assert config.state_adapter is None
