"""Framework-internal data types.

These are deliberately plain dataclasses with no dependency on config models or
external SDKs so they can be imported anywhere without creating import cycles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Literal

#: Version of the :class:`AgentTrajectory` payload shape. Deliberately *independent*
#: of ``eval_harness.version.SCHEMA_VERSION``, which versions the config schema and is
#: bumped only in dedicated release commits (see ``docs/CHARTER.md`` §3).
TRAJECTORY_SCHEMA_VERSION = "1.0.0"

#: The kinds of step an agent trajectory can contain, in the order they typically occur.
StepKind = Literal["model_decision", "tool_call", "tool_observation", "tool_error", "final"]


@dataclass
class EvalItem:
    """A single evaluation case loaded from a dataset source."""

    id: str
    inputs: dict[str, Any]
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _freeze(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a read-only view of *mapping*.

    ``frozen=True`` blocks attribute rebinding but not in-place mutation of a dict field,
    so without this a caller could do ``record.arguments["k"] = v`` and change the record's
    canonical form after construction. Wrapping once at construction makes the immutability
    these docstrings promise actually hold.
    """
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool invocation: the tool's name and the arguments it was called with.

    ``call_id`` is the provider's correlation id when one exists. It is *not* part
    of the identity used for matching — two calls that differ only by ``call_id``
    are the same call — so trajectories stay comparable across runs.

    ``arguments`` is stored as a read-only mapping, so a constructed record cannot
    change its own canonical form.
    """

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    def __post_init__(self) -> None:
        # object.__setattr__ is the standard frozen-dataclass idiom for normalising a
        # field at construction.
        object.__setattr__(self, "arguments", _freeze(self.arguments))


@dataclass(frozen=True)
class TrajectoryStep:
    """One step of an agent's execution path.

    ``tool_call`` is populated for ``tool_call`` steps and for the ``tool_observation``
    / ``tool_error`` steps that answer them, so an observation can be attributed to
    the call it came from without relying on positional adjacency.
    """

    kind: StepKind
    timestamp_ms: int | None = None
    tool_call: ToolCallRecord | None = None
    content: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze(self.metadata))


@dataclass(frozen=True)
class AgentTrajectory:
    """The ordered execution path a target took to produce its output.

    Immutable, and target-owned: the target that made the tool calls constructs this.
    The harness never reconstructs a trajectory from tracing spans — that would put a
    network dependency on the offline evaluation path.
    """

    steps: tuple[TrajectoryStep, ...] = ()
    schema_version: str = TRAJECTORY_SCHEMA_VERSION

    def tool_calls(self) -> tuple[ToolCallRecord, ...]:
        """Every tool call in execution order, duplicates preserved.

        Duplicates carry the precision and loop signal, so they are never collapsed
        here; scorers that want set semantics apply them themselves.
        """
        return tuple(s.tool_call for s in self.steps if s.kind == "tool_call" and s.tool_call is not None)


@dataclass
class TargetOutput:
    """The result of running the system-under-test against one item.

    ``trajectory`` is appended last and defaults to ``None`` so existing targets,
    positional construction, and historical results all keep working unchanged
    (see ADR 0031).
    """

    output: Any
    latency_ms: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trajectory: AgentTrajectory | None = None


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
    """One target run against one item, plus its scores.

    ``attempt_index``, ``attempt_id`` and ``item_run_id`` are appended last and
    default to ``None`` — the legacy, single-attempt shape (``repetitions=1``) — so
    existing positional construction and historical result JSON keep working
    unchanged (mirrors the ``trajectory`` precedent, ADR 0031). The engine sets all
    three together only when ``repetitions > 1``; they are never populated
    independently of one another.
    """

    item: EvalItem
    output: TargetOutput
    scores: list[ScoreResult] = field(default_factory=list)
    attempt_index: int | None = None
    attempt_id: str | None = None
    item_run_id: str | None = None


@dataclass
class ScoreAggregate:
    count: int
    mean: float
    pass_rate: float | None


@dataclass(frozen=True)
class GateRuleRecord:
    """One gate rule's outcome, as data rather than as a formatted sentence.

    A soak's whole purpose is diffing a gate's verdict across runs, and a
    rendered string cannot be diffed on the field that changed — the same
    reasoning that makes ``RunResult.diagnostics`` a list of mappings rather
    than log lines.

    ``observed`` is ``None`` when the rule could not be evaluated at all (the
    named score is absent, or carries no value for the requested metric). That
    is deliberately distinct from an observed value that missed its bound:
    "could not measure" and "measured and failed" are different facts, and
    collapsing them is how a gate comes to report a pass having measured
    nothing (ADR 0029).

    ``detail`` carries the human-readable rendering so a reader never has to
    reconstruct it, and so the CLI and the sinks cannot drift apart on wording.
    """

    score: str
    metric: str
    observed: float | None
    minimum: float | None
    maximum: float | None
    met: bool
    advisory: bool
    detail: str


@dataclass(frozen=True)
class GateDecision:
    """What the quality gate decided about a run, carried on the run itself.

    Lives in ``core`` rather than in ``gating`` so that ``RunResult`` can name
    it without inverting the dependency direction: ``core`` imports nothing
    from its siblings, ``gating`` imports ``core``, and the engine imports
    both.

    ``blocking_failures`` and ``advisory_failures`` are separate lists rather
    than one list with a flag because every consumer treats them differently —
    the process exit code reads only the first, a soak report reads only the
    second — and a single list invites a consumer to forget the distinction.
    """

    passed: bool
    blocking_failures: list[str] = field(default_factory=list)
    advisory_failures: list[str] = field(default_factory=list)
    rules: list[GateRuleRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Render as JSON-ready plain data for sinks and result payloads."""
        return {
            "passed": self.passed,
            "blocking_failures": list(self.blocking_failures),
            "advisory_failures": list(self.advisory_failures),
            "rules": [
                {
                    "score": r.score,
                    "metric": r.metric,
                    "observed": r.observed,
                    "min": r.minimum,
                    "max": r.maximum,
                    "met": r.met,
                    "advisory": r.advisory,
                    "detail": r.detail,
                }
                for r in self.rules
            ],
        }


@dataclass
class RunResult:
    """Appended last: ``diagnostics``, defaulting to ``[]`` so historical positional
    construction and byte-identical serialization at ``repetitions=1`` both hold
    (ADR 0031 obligation 1/4, extended to reliability diagnostics)."""

    run_id: str
    config_name: str
    items: list[ItemResult]
    aggregate: dict[str, ScoreAggregate]
    started_at: datetime
    finished_at: datetime
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    #: The quality gate's verdict on this run, attached by the engine before the
    #: sinks are emitted so that every exported artifact carries it. ``None``
    #: when no gate is configured — and, as with ``diagnostics``, the key is then
    #: omitted from ``to_dict()`` entirely, so an ungated run serializes
    #: byte-identically to the pre-change payload (ADR 0031 obligation 4).
    gate: GateDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "config_name": self.config_name,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "aggregate": {
                k: {"count": v.count, "mean": v.mean, "pass_rate": v.pass_rate} for k, v in self.aggregate.items()
            },
            "items": [self._item_to_dict(ir) for ir in self.items],
        }
        if self.diagnostics:
            payload["reliability"] = {"diagnostics": self.diagnostics}
        if self.gate is not None:
            payload["gate"] = self.gate.to_dict()
        return payload

    @staticmethod
    def _item_to_dict(ir: ItemResult) -> dict[str, Any]:
        """Serialize one item result.

        ``trajectory`` is emitted only when the target produced one, and the
        attempt-identity keys only when the engine populated them (``repetitions >
        1``), so a `repetitions=1` run serializes byte-identically to the
        pre-reliability-metrics harness (ADR 0031 obligation 4; same contract
        extended to attempt identity).
        """
        payload: dict[str, Any] = {
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
                    "metadata": s.metadata,
                }
                for s in ir.scores
            ],
        }
        if ir.output.trajectory is not None:
            payload["trajectory"] = trajectory_to_dict(ir.output.trajectory)
        if ir.attempt_index is not None:
            payload["attempt_index"] = ir.attempt_index
            payload["attempt_id"] = ir.attempt_id
            payload["item_run_id"] = ir.item_run_id
        return payload


def trajectory_to_dict(trajectory: AgentTrajectory) -> dict[str, Any]:
    """Render an :class:`AgentTrajectory` as JSON-ready plain data.

    Per-step keys that carry no information (an absent tool call, an absent
    timestamp, empty metadata) are omitted rather than emitted as nulls, so the
    payload stays readable for the common text-and-tools case.
    """
    steps: list[dict[str, Any]] = []
    for step in trajectory.steps:
        rendered: dict[str, Any] = {"kind": step.kind}
        if step.timestamp_ms is not None:
            rendered["timestamp_ms"] = step.timestamp_ms
        if step.tool_call is not None:
            call: dict[str, Any] = {"name": step.tool_call.name, "arguments": dict(step.tool_call.arguments)}
            if step.tool_call.call_id is not None:
                call["call_id"] = step.tool_call.call_id
            rendered["tool_call"] = call
        if step.content is not None:
            rendered["content"] = step.content
        if step.metadata:
            rendered["metadata"] = dict(step.metadata)
        steps.append(rendered)
    return {"schema_version": trajectory.schema_version, "steps": steps}


@dataclass(frozen=True)
class StateSnapshot:
    """Opaque, adapter-owned capture of world state at one instant.

    Only the ``StateAdapter`` that produced a snapshot interprets ``data``'s
    shape — the engine and scorers treat it as an opaque comparison unit.
    Frozen, with ``data`` wrapped read-only (mirrors ``ToolCallRecord.arguments``),
    so a captured snapshot cannot be mutated after the fact — before/after
    comparison would be meaningless otherwise.
    """

    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", _freeze(self.data))


@dataclass(frozen=True)
class StateEvaluation:
    """A ``StateAdapter``'s verdict on one before/after state transition.

    ``goal_reached`` and ``policy_violated`` are two independent axes, not
    collapsed into one ``passed`` bool: an attempt can reach its goal via a
    forbidden mutation (``goal_reached=True``, ``policy_violated=True``), and
    the two consuming scorers each read a different axis — the deterministic
    state-transition scorer reads ``goal_reached``, the policy-violation
    scorer reads ``policy_violated`` — so neither outcome can mask the other.
    """

    goal_reached: bool
    policy_violated: bool = False
    reasoning: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze(self.metadata))


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
    item_index: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
