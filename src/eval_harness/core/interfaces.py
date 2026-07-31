"""Stable, structural interfaces for every pluggable component.

Implementations are free to evolve as long as these method signatures hold,
which is the contract that lets new component versions stay drop-in compatible.
Declared as ``typing.Protocol`` (not ``abc.ABC``) so DI seams are structural: a
fake used in tests satisfies the interface by shape alone and need not inherit
from it, while existing implementations that do explicitly subclass these
classes keep working unchanged (explicit inheritance from a ``Protocol`` is
ordinary nominal inheritance, including any concrete methods it defines).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .types import EvalItem, JudgeVerdict, RunContext, RunResult, ScoreResult, TargetOutput


class Scorer(Protocol):
    """Scores a single (item, output) pair. ``name`` labels the emitted score.

    Not ``@runtime_checkable``: it carries a non-method member (``default_name``),
    and ``typing.Protocol`` only supports ``isinstance``/``issubclass`` checks for
    protocols whose members are all methods. Structural conformance here is
    enforced by explicit nominal inheritance (every built-in scorer subclasses
    this directly) rather than a runtime structural check.
    """

    default_name: str = "score"
    name: str

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
