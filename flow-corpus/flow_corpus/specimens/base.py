# pyright: reportMissingImports=false
"""Specimen protocol, a shared base, and a minimal generic registry.

A *specimen* is one agentic flow variant. It runs a task instance against an
injected :class:`~flow_corpus.policy.base.Policy` and emits a
:class:`flow_protocol.FlowResult`. Its ``agent_version`` is ``hash(impl + agent_config)``
— the task is never part of the key.
"""

from __future__ import annotations

import random
from contextlib import suppress
from dataclasses import dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from flow_corpus.keying import version_key
from flow_corpus.policy.base import Policy
from flow_corpus.suites.base import TaskInstance

T = TypeVar("T")


if TYPE_CHECKING:
    from flow_protocol import FlowResult
else:

    @dataclass(frozen=True, slots=True)
    class FlowResult:
        instance_id: str
        flow_type: str
        agent_version: str
        domain: str
        output: Any
        raw_confidence: float | None
        seed: int | None

        def model_copy(self, *, update: dict[str, Any] | None = None) -> FlowResult:
            return replace(self, **(update or {}))


_FlowResultFactory: Any = FlowResult


with suppress(ImportError, AttributeError):
    _FlowResultFactory = import_module("flow_protocol").FlowResult


def copy_flow_result(result: FlowResult, update: dict[str, Any]) -> FlowResult:
    """Return ``result`` with ``update`` applied across protocol/fallback variants."""
    try:
        return result.model_copy(update=update)
    except AttributeError:  # pragma: no cover - pydantic v1 compatibility
        return cast(FlowResult, cast(Any, result).copy(update=update))


class Registry(Generic[T]):
    """Tiny name → factory registry (self-contained; no harness dependency)."""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._factories: dict[str, T] = {}

    def register(self, name: str, factory: T) -> None:
        if name in self._factories:
            raise ValueError(f"{self._kind} {name!r} already registered")
        self._factories[name] = factory

    def get(self, name: str) -> T:
        try:
            return self._factories[name]
        except KeyError:
            raise KeyError(f"unknown {self._kind}: {name!r}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


@runtime_checkable
class Specimen(Protocol):
    flow_type: str

    @property
    def agent_version(self) -> str: ...

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult: ...


class SpecimenBase:
    """Shared base: computes the version key and assembles the FlowResult."""

    flow_type: str = "base"
    impl_version: str = "1"

    def __init__(self, policy: Policy, agent_config: dict[str, object] | None = None) -> None:
        self.policy = policy
        self.agent_config: dict[str, object] = dict(agent_config or {})

    @property
    def impl_id(self) -> str:
        return f"{self.flow_type}@{self.impl_version}"

    @property
    def agent_version(self) -> str:
        return version_key(self.impl_id, self.agent_config)

    def _result(
        self,
        instance: TaskInstance,
        candidate: str,
        confidence: float | None,
        seed: int | None,
    ) -> FlowResult:
        return cast(
            FlowResult,
            _FlowResultFactory(
                instance_id=instance.instance_id,
                flow_type=self.flow_type,
                agent_version=self.agent_version,
                domain=instance.domain,
                output=candidate,
                raw_confidence=confidence,
                seed=seed,
            ),
        )

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:  # pragma: no cover
        _ = (instance, rng)
        raise NotImplementedError
