"""Stable, structural interfaces for every pluggable component.

Implementations are free to evolve as long as these method signatures hold,
which is the contract that lets new component versions stay drop-in compatible.
Four of five are declared as ``typing.Protocol`` (not ``abc.ABC``) so those DI
seams are structural: a fake used in tests satisfies the interface by shape
alone and need not inherit from it, while existing implementations that do
explicitly subclass these classes keep working unchanged (explicit inheritance
from a ``Protocol`` is ordinary nominal inheritance, including any concrete
methods it defines).

``Scorer`` is the one exception, and stays ``abc.ABC``: it is the only one of
the five with a concrete, inherited ``__init__`` (the shared ``name``/
``default_name`` bookkeeping every built-in scorer relies on without
redefining its own constructor). ``typing.Protocol.__init__`` does not
reliably propagate a Protocol base's own ``__init__`` to subclasses that don't
define their own on Python 3.10 (this repo's CI matrix includes 3.10; fixed in
3.11+) — confirmed by a concrete regression: converting ``Scorer`` to
``Protocol`` silently left every built-in scorer's ``.name`` unset under 3.10.
See ``docs/CHARTER.md`` §4 invariant 3 for how the charter documents this
exception.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .types import EvalItem, JudgeVerdict, RunContext, RunResult, ScoreResult, TargetOutput


class Scorer(ABC):
    """Scores a single (item, output) pair. ``name`` labels the emitted score."""

    default_name: str = "score"

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.default_name

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
    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict: ...
