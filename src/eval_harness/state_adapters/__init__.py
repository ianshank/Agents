"""Built-in state adapters.

Every adapter here is local and deterministic: in-memory mapping, filesystem
sandbox, SQLite transaction, in-process mock HTTP. The offline suite's
zero-external-dependency property holds — no production credentials and no
domain-specific adapters ship in this package; those arrive later behind the
same ``StateAdapter`` seam (``core/interfaces.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..core.interfaces import StateAdapter
from ..core.types import EvalItem, RunContext, StateEvaluation, StateSnapshot
from ..plugins import STATE_ADAPTERS


@STATE_ADAPTERS.register("in_memory")
class InMemoryStateAdapter(StateAdapter):
    """A mutable in-memory key/value store, reset to its initial state per attempt.

    The reference, simplest adapter: no I/O, fully deterministic. Whatever
    drives world-state changes during ``target.run(item)`` — typically the
    target itself, holding a reference to the same adapter instance — calls
    :meth:`set`/:meth:`update` directly; the adapter does not intercept or
    observe the target's execution, only what it is told.

    ``evaluate`` reads two optional, per-item conventions from
    ``item.metadata`` (mirrors ``TrajectoryStepEfficiencyScorer``'s
    ``step_budget`` convention — no new ``EvalItem`` field):

    * ``state_expectation``: a mapping of keys to their expected value after
      the attempt. ``goal_reached`` is true when every declared key matches.
      Absent entirely, ``goal_reached`` reports whether the store changed at
      all (a bare "did anything happen" signal).
    * ``state_forbidden_keys``: keys that must not change. ``policy_violated``
      is true when any of them did — independent of ``goal_reached``, so an
      attempt can reach its declared goal via a forbidden mutation.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._initial: dict[str, Any] = dict(initial or {})
        self._store: dict[str, Any] = dict(self._initial)

    def set(self, key: str, value: Any) -> None:
        """Write one key — the adapter's own mutation surface."""
        self._store[key] = value

    def update(self, values: Mapping[str, Any]) -> None:
        """Write several keys at once."""
        self._store.update(values)

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        return StateSnapshot(data=dict(self._store))

    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
        expectation = item.metadata.get("state_expectation")
        if expectation is not None and not isinstance(expectation, Mapping):
            raise TypeError(
                f"item {item.id!r}: state_expectation must be a mapping, got {type(expectation).__name__}"
            )
        forbidden = item.metadata.get("state_forbidden_keys", ())
        if not isinstance(forbidden, Iterable) or isinstance(forbidden, (str, bytes)):
            raise TypeError(
                f"item {item.id!r}: state_forbidden_keys must be an iterable of keys, "
                f"got {type(forbidden).__name__}"
            )

        if expectation:
            goal_reached = all(after.data.get(k) == v for k, v in expectation.items())
            reasoning = "state_expectation met" if goal_reached else "state_expectation not met"
        else:
            goal_reached = after.data != before.data
            reasoning = "no state_expectation declared; goal_reached reports whether the store changed"

        violated_keys = [k for k in forbidden if before.data.get(k) != after.data.get(k)]
        policy_violated = bool(violated_keys)
        if policy_violated:
            reasoning = f"{reasoning}; forbidden keys mutated: {violated_keys}"

        return StateEvaluation(
            goal_reached=goal_reached,
            policy_violated=policy_violated,
            reasoning=reasoning,
            metadata={"before": dict(before.data), "after": dict(after.data)},
        )

    def reset(self, ctx: RunContext) -> None:
        self._store = dict(self._initial)
