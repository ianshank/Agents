"""Stable, abstract interfaces for every pluggable component.

Implementations are free to evolve as long as these method signatures hold,
which is the contract that lets new component versions stay drop-in compatible.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from .types import EvalItem, JudgeVerdict, RunContext, RunResult, ScoreResult, TargetOutput


class Scorer(ABC):
    """Scores a single (item, output) pair. ``name`` labels the emitted score."""

    default_name: str = "score"

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.default_name

    @abstractmethod
    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        ...


class DatasetSource(ABC):
    @abstractmethod
    def load(self) -> Iterable[EvalItem]:
        ...


class TargetRunner(ABC):
    """The system-under-test adapter."""

    @abstractmethod
    def run(self, item: EvalItem) -> TargetOutput:
        ...


class ResultSink(ABC):
    @abstractmethod
    def emit(self, run: RunResult) -> None:
        ...


class Judge(ABC):
    """LLM-as-judge abstraction. Implementations call a model; tests use a mock."""

    @abstractmethod
    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        ...
