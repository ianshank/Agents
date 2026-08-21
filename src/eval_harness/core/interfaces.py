"""Stable, structural interfaces for every pluggable component.

Implementations are free to evolve as long as these method signatures hold,
which is the contract that lets new component versions stay drop-in compatible.
All six interfaces are declared as ``typing.Protocol`` (not ``abc.ABC``) so
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

from .types import (
    EvalItem,
    JudgeVerdict,
    RunContext,
    RunResult,
    ScoreResult,
    StateEvaluation,
    StateSnapshot,
    TargetOutput,
)


@runtime_checkable
class Scorer(Protocol):
    """Scores a single (item, output) pair. ``name`` labels the emitted score."""

    name: str

    def __init__(self, name: str | None = None) -> None:
        default: str = str(getattr(self, "default_name", "score"))
        self.name = name if name is not None else default

    @abstractmethod
    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult: ...

    def uses_judge(self) -> bool:
        """Whether this scorer's verdict depends on a ``Judge`` call, directly or
        (for a composite) through a child scorer.

        A plain method, not a ``@property`` — see ``TargetRunner.is_deterministic``'s
        docstring for why a ``runtime_checkable`` Protocol needs every member callable.
        ``False`` by default and non-abstract, so every existing scorer — including
        ones that predate this method — stays a valid ``Scorer`` unchanged. The engine
        orders judge-backed scorers after every other scorer and skips them once a
        programmatic scorer has already failed the item (F-057: a judge's verdict
        cannot convert an already-failed item into a pass).
        """
        return False


def _uses_judge(scorer: Scorer) -> bool:
    """Whether *scorer* is judge-backed; tolerates one predating ``Scorer.uses_judge``.

    Shared by ``engine.py`` (scorer ordering, the judge-skip guard) and ``gating``
    (calibration-artifact enforcement) — both need the exact same duck-typed
    fallback, so it lives once next to the ``uses_judge()`` method it wraps.
    """
    method = getattr(scorer, "uses_judge", None)
    return bool(method()) if callable(method) else False


@runtime_checkable
class DatasetSource(Protocol):
    @abstractmethod
    def load(self) -> Iterable[EvalItem]: ...


@runtime_checkable
class TargetRunner(Protocol):
    """The system-under-test adapter."""

    @abstractmethod
    def run(self, item: EvalItem) -> TargetOutput: ...

    def is_deterministic(self) -> bool | None:
        """Whether repeated ``run()`` calls on the same item return the same output.

        A plain method, not a ``@property``: a ``runtime_checkable`` Protocol's
        ``issubclass()`` support requires every member to be callable
        (``typing``'s ``_is_callable_members_only``) — a data-descriptor member
        would raise ``TypeError`` at ``issubclass(SomeTarget, TargetRunner)``,
        which ``tests/test_matrix_eval_tools.py``'s ``TestM4Interface`` exercises
        for every registered target.

        ``None`` (the default) means undeclared, never an implicit ``False`` — the
        engine falls back to observing actual attempt outputs when this is unknown.
        Concrete and non-abstract, so every existing target — including ones that
        predate this method and never override it — stays a valid ``TargetRunner``
        unchanged (ADR 0031 obligation 1). Targets that know their own sampling
        behaviour override it, e.g. ``ModelTarget`` from ``temperature == 0.0``.
        """
        return None


@runtime_checkable
class ResultSink(Protocol):
    @abstractmethod
    def emit(self, run: RunResult) -> None: ...


@runtime_checkable
class Judge(Protocol):
    """LLM-as-judge abstraction. Implementations call a model; tests use a mock."""

    @abstractmethod
    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict: ...


class StateSnapshotError(RuntimeError):
    """Wraps a ``StateAdapter.snapshot()``/``evaluate()`` failure.

    Always fails just the item: caught inside ``EvalEngine._run_one`` and
    reported as a synthetic failing score, never propagated, regardless of
    ``fail_fast``. A state check that silently degrades to "no opinion" on
    adapter failure is worse than no state check at all (``design.md``
    "Failure semantics") — the item must visibly fail, not vanish the way an
    uncaught target error can under parallel execution with ``fail_fast=False``.
    """


class StateResetError(RuntimeError):
    """Wraps a ``StateAdapter.reset()`` failure.

    Always aborts the run: continuing would score subsequent attempts against
    contaminated state (``design.md`` "Failure semantics"). Never
    ``fail_fast``-gated, unlike every other engine failure path — propagates
    uncaught out of ``EvalEngine._run_one``, and ``_run_one_safe``/
    ``_run_parallel`` are taught to re-raise rather than swallow it.
    """


@runtime_checkable
class StateAdapter(Protocol):
    """Captures and judges world-state transitions the target's own account can't be trusted for.

    An agent that reports success without changing anything scores identically
    to one that actually acted, under any scorer that only reads
    ``output.output``. This is the seam that closes that gap.

    The **engine** owns this Protocol's lifecycle, not the target:
    ``TargetRunner.run`` takes no context parameter, so there is nowhere on
    the target to hang before/after capture. Per attempt: ``reset ->
    snapshot(before) -> target.run(item) -> snapshot(after) -> evaluate``.
    """

    @abstractmethod
    def snapshot(self, ctx: RunContext) -> StateSnapshot: ...

    @abstractmethod
    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation: ...

    @abstractmethod
    def reset(self, ctx: RunContext) -> None: ...
