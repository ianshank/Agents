"""Framework-internal data types.

These are deliberately plain dataclasses with no dependency on config models or
external SDKs so they can be imported anywhere without creating import cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EvalItem:
    """A single evaluation case loaded from a dataset source."""

    id: str
    inputs: dict[str, Any]
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetOutput:
    """The result of running the system-under-test against one item."""

    output: Any
    latency_ms: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreResult:
    """A single scorer's verdict for one item."""

    name: str
    value: float
    passed: bool | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgeVerdict:
    """Normalised output of an LLM-as-judge call."""

    score: float
    reasoning: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ItemResult:
    item: EvalItem
    output: TargetOutput
    scores: list[ScoreResult] = field(default_factory=list)


@dataclass
class ScoreAggregate:
    count: int
    mean: float
    pass_rate: float | None


@dataclass
class RunResult:
    run_id: str
    config_name: str
    items: list[ItemResult]
    aggregate: dict[str, ScoreAggregate]
    started_at: datetime
    finished_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config_name": self.config_name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "aggregate": {
                k: {"count": v.count, "mean": v.mean, "pass_rate": v.pass_rate} for k, v in self.aggregate.items()
            },
            "items": [
                {
                    "id": ir.item.id,
                    "inputs": ir.item.inputs,
                    "expected": ir.item.expected,
                    "output": ir.output.output,
                    "error": ir.output.error,
                    "latency_ms": ir.output.latency_ms,
                    "scores": [
                        {
                            "name": s.name,
                            "value": s.value,
                            "passed": s.passed,
                            "comment": s.comment,
                        }
                        for s in ir.scores
                    ],
                }
                for ir in self.items
            ],
        }


@dataclass
class RunContext:
    """Per-run context threaded into every scorer call.

    Carries shared, injected collaborators (judge, RNG, clock) so that nothing
    has to be constructed with hard-coded globals and runs stay deterministic.
    """

    config: Any
    judge: Any = None
    rng: Any = None
    now: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)
