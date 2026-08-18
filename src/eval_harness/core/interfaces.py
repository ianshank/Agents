"""Stable, structural interfaces for every pluggable component.

Implementations are free to evolve as long as these method signatures hold,
which is the contract that lets new component versions stay drop-in compatible.
All five interfaces are declared as ``typing.Protocol`` (not ``abc.ABC``) so
every DI seam is structural: a fake used in tests satisfies the interface by
shape alone and need not inherit from it, while existing implementations that
do explicitly subclass these classes keep working unchanged (explicit
inheritance from a ``Protocol`` is ordinary nominal inheritance, including any
concrete methods it defines).

``Scorer`` was the last ``abc.ABC`` holdout — its concrete ``__init__`` (the
shared ``name``/``default_name`` bookkeeping every built-in scorer relies on
without redefining its own constructor) did not propagate reliably to Protocol
subclasses on Python 3.10. With the 3.10 floor dropped (ADR 0034 raised
``requires-python`` to ``>=3.11``), the 3.11 fix for ``Protocol.__init__``
propagation is universally available and the migration is safe.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from .types import EvalItem, JudgeVerdict, RunContext, RunResult, ScoreResult, TargetOutput


@runtime_checkable
class Scorer(Protocol):
    """Scores a single (item, output) pair. ``name`` labels the emitted score."""

    name: str

    def __init__(self, name: str | None = None) -> None:
        default: str = str(getattr(self, "default_name", "score"))
        self.name = name if name is not None else default

    @abstractmethod
    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult: ...


@runtime_checkable
class DatasetSource(Protocol):
    @abstractmethod
    def load(self) -> Iterable[EvalItem]: ...


@runtime_checkable
class TargetRunner(Protocol):
    """The system-under-test adapter."""

    @abstractmethod
    def run(self, item: EvalItem) -> TargetOutput: ...


@runtime_checkable
class ResultSink(Protocol):
    @abstractmethod
    def emit(self, run: RunResult) -> None: ...


@runtime_checkable
class Judge(Protocol):
    """LLM-as-judge abstraction. Implementations call a model; tests use a mock."""

    @abstractmethod
    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict: ...
