"""Scorers that grade *how* an agent reached its answer, not just the answer.

Every scorer here reads ``TargetOutput.trajectory``. A target that emits none is not
failed: the verdict is ``passed=None`` with an explanatory comment, matching the
convention ``AutoevalsScorer`` established for a skipped scorer. That distinction
matters — ``EvalEngine._aggregate`` excludes ``None`` verdicts from ``pass_rate``, so
a text-only target scored by a trajectory scorer no longer silently drags the pass
rate to zero. The emitted *value* still enters the mean, which is why ``on_missing``
is an operator-facing knob rather than a hidden constant.

Kept in its own module rather than in ``scorers/__init__.py``: that file is near the
500-line hard ceiling enforced by ``scripts/check_size_budget.py``, and this is seven
more scorers. ``scorers/__init__.py`` imports this module so the registrations run,
mirroring how ``targets/__init__.py`` imports ``targets/model.py``.

Reference trajectories come from ``item.expected``. Two shapes are accepted: a bare
list of tool calls, or a mapping with a ``tool_calls`` key (so an expectation can carry
other fields alongside). Each call is either a plain name or a ``{name, arguments}``
mapping.
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

from ..core._trajectory import (
    CanonicalCall,
    NormalizationConfig,
    canonical_calls,
    is_subsequence,
)
from ..core.interfaces import Scorer
from ..core.types import AgentTrajectory, EvalItem, RunContext, ScoreResult, TargetOutput, ToolCallRecord
from ..plugins import SCORERS

#: Comment emitted when a scorer needs a trajectory and the target produced none.
_NO_TRAJECTORY = "no trajectory on target output; scorer not applicable"

#: Comment emitted when a reference trajectory is required but the item declares none.
_NO_REFERENCE = "item declares no reference trajectory; scorer not applicable"


class _TrajectoryScorer(Scorer):
    """Shared plumbing: normalization config, the not-applicable verdict, and
    reference-trajectory parsing.

    Subclasses implement :meth:`_score_calls` (reference-matching scorers) or override
    :meth:`score` outright (quality scorers, which need no reference).
    """

    #: Whether this scorer needs ``item.expected`` to contain a reference trajectory.
    requires_reference: bool = True

    def __init__(
        self,
        name: str | None = None,
        case_sensitive_names: bool = False,
        strip_names: bool = True,
        ignore_fields: list[str] | None = None,
        compare_arguments: bool = True,
        on_missing: float = 0.0,
    ):
        super().__init__(name)
        self.normalization = NormalizationConfig(
            case_sensitive_names=case_sensitive_names,
            strip_names=strip_names,
            ignore_fields=frozenset(ignore_fields or ()),
            compare_arguments=compare_arguments,
        )
        self.on_missing = float(on_missing)

    def _not_applicable(self, comment: str) -> ScoreResult:
        """The verdict for 'this scorer had nothing to grade'."""
        return ScoreResult(self.name, value=self.on_missing, passed=None, comment=comment)

    def _reference_calls(self, item: EvalItem) -> tuple[CanonicalCall, ...] | None:
        """Canonical reference calls from ``item.expected``, or None if it declares none."""
        expected: Any = item.expected
        if isinstance(expected, dict):
            expected = expected.get("tool_calls")
        if expected is None or not isinstance(expected, (list, tuple)):
            return None
        records: list[ToolCallRecord] = []
        for entry in expected:
            if isinstance(entry, ToolCallRecord):
                records.append(entry)
            elif isinstance(entry, str):
                records.append(ToolCallRecord(name=entry))
            elif isinstance(entry, dict) and "name" in entry:
                records.append(ToolCallRecord(name=str(entry["name"]), arguments=entry.get("arguments", {})))
            else:
                return None
        return canonical_calls(records, self.normalization)

    def _candidate_calls(self, trajectory: AgentTrajectory) -> tuple[CanonicalCall, ...]:
        return canonical_calls(trajectory.tool_calls(), self.normalization)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        trajectory = output.trajectory
        if trajectory is None:
            return self._not_applicable(_NO_TRAJECTORY)
        # The narrowed trajectory is threaded into the subclass hooks rather than
        # re-derived behind an assert: asserts vanish under `python -O`, which would
        # turn this guard into an AttributeError deep inside a scorer.
        if not self.requires_reference:
            return self._score_quality(item, trajectory)
        reference = self._reference_calls(item)
        if reference is None:
            return self._not_applicable(_NO_REFERENCE)
        return self._score_calls(reference, self._candidate_calls(trajectory))

    def _score_calls(
        self,
        reference: tuple[CanonicalCall, ...],
        candidate: tuple[CanonicalCall, ...],
    ) -> ScoreResult:  # pragma: no cover - overridden by reference-matching scorers
        raise NotImplementedError

    def _score_quality(
        self, item: EvalItem, trajectory: AgentTrajectory
    ) -> ScoreResult:  # pragma: no cover - overridden by quality scorers
        raise NotImplementedError


def _names(calls: tuple[CanonicalCall, ...]) -> list[str]:
    """Tool names in order, for human-readable comments.

    These are the *canonical* names — lowercased and stripped under the default
    config — because they are what the comparison actually used. A reference written
    as ``Search`` is reported as ``search``; that is deliberate, so a diagnostic never
    implies a match was attempted on a form that was not.
    """
    return [name for name, _ in calls]


@SCORERS.register("trajectory_exact", aliases=("trajectory-exact",))
class TrajectoryExactScorer(_TrajectoryScorer):
    """Same calls, same order, nothing extra.

    The strictest mode, and the least broadly applicable: most real tasks admit more
    than one correct path. Reach for ``trajectory_in_order`` or
    ``trajectory_any_order`` unless the sequence really is the specification.
    """

    default_name = "trajectory_exact"

    def _score_calls(
        self,
        reference: tuple[CanonicalCall, ...],
        candidate: tuple[CanonicalCall, ...],
    ) -> ScoreResult:
        match = reference == candidate
        comment = None if match else f"expected {_names(reference)}, got {_names(candidate)}"
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match, comment=comment)


@SCORERS.register("trajectory_in_order", aliases=("trajectory-in-order",))
class TrajectoryInOrderScorer(_TrajectoryScorer):
    """Every reference call appears, in order. Extra calls are tolerated."""

    default_name = "trajectory_in_order"

    def _score_calls(
        self,
        reference: tuple[CanonicalCall, ...],
        candidate: tuple[CanonicalCall, ...],
    ) -> ScoreResult:
        match = is_subsequence(reference, candidate)
        comment = None if match else f"{_names(reference)} is not an ordered subsequence of {_names(candidate)}"
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match, comment=comment)


@SCORERS.register("trajectory_any_order", aliases=("trajectory-any-order",))
class TrajectoryAnyOrderScorer(_TrajectoryScorer):
    """Every required call appears the required number of times; order ignored.

    Multiset, not set: a reference asking for two lookups is not satisfied by one.
    """

    default_name = "trajectory_any_order"

    def _score_calls(
        self,
        reference: tuple[CanonicalCall, ...],
        candidate: tuple[CanonicalCall, ...],
    ) -> ScoreResult:
        missing = Counter(reference) - Counter(candidate)
        match = not missing
        comment = None if match else f"missing calls: {sorted(name for name, _ in missing.elements())}"
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match, comment=comment)


@SCORERS.register("trajectory_precision_recall", aliases=("trajectory-precision-recall",))
class TrajectoryPrecisionRecallScorer(_TrajectoryScorer):
    """Multiset overlap between reference and candidate calls.

    Precision and recall are reported *separately* in ``metadata`` because they mean
    different things: low precision is wasted or unsafe work, low recall is work left
    undone. The emitted value is their F1, so a single number still ranks sensibly.
    """

    default_name = "trajectory_precision_recall"

    def __init__(self, name: str | None = None, pass_threshold: float = 1.0, **kwargs: Any):
        super().__init__(name, **kwargs)
        self.pass_threshold = float(pass_threshold)

    def _score_calls(
        self,
        reference: tuple[CanonicalCall, ...],
        candidate: tuple[CanonicalCall, ...],
    ) -> ScoreResult:
        ref_counts, cand_counts = Counter(reference), Counter(candidate)
        overlap = sum((ref_counts & cand_counts).values())
        precision = overlap / len(candidate) if candidate else (1.0 if not reference else 0.0)
        recall = overlap / len(reference) if reference else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return ScoreResult(
            self.name,
            value=f1,
            passed=f1 >= self.pass_threshold,
            comment=f"precision={precision:.3f} recall={recall:.3f}",
            metadata={
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "matched": overlap,
                "candidate_calls": len(candidate),
                "reference_calls": len(reference),
            },
        )


@SCORERS.register("trajectory_step_efficiency", aliases=("trajectory-step-efficiency",))
class TrajectoryStepEfficiencyScorer(_TrajectoryScorer):
    """How much work the agent did against a budget, independent of correctness.

    A trajectory can reach the right answer wastefully. This scorer exists so that
    outcome success and efficiency are visible as two separate facts rather than one
    blended verdict.

    The budget comes from ``item.metadata['step_budget']`` when present, else from the
    configured ``budget``. ``count`` selects what is counted: tool calls (default) or
    every step.
    """

    default_name = "trajectory_step_efficiency"
    requires_reference = False

    _COUNT_MODES = ("tool_calls", "steps")

    def __init__(
        self,
        name: str | None = None,
        budget: int | None = None,
        count: str = "tool_calls",
        budget_key: str = "step_budget",
        **kwargs: Any,
    ):
        super().__init__(name, **kwargs)
        if count not in self._COUNT_MODES:
            raise ValueError(f"unknown count mode {count!r}; supported: {list(self._COUNT_MODES)}")
        if budget is not None and budget <= 0:
            raise ValueError(f"budget must be > 0; got {budget}")
        self.budget = budget
        self.count = count
        self.budget_key = budget_key

    def _score_quality(self, item: EvalItem, trajectory: AgentTrajectory) -> ScoreResult:
        budget = item.metadata.get(self.budget_key, self.budget)
        if budget is None:
            return self._not_applicable("no step budget configured or declared on the item")
        budget = int(budget)
        if budget <= 0:
            return self._not_applicable(f"declared step budget must be > 0; got {budget}")
        actual = len(trajectory.tool_calls()) if self.count == "tool_calls" else len(trajectory.steps)
        # Ratio of budget to actual, capped at 1.0: finishing under budget is not
        # rewarded above finishing at it, but overrun degrades proportionally.
        value = 1.0 if actual <= budget else budget / actual
        within = actual <= budget
        return ScoreResult(
            self.name,
            value=value,
            passed=within,
            comment=None if within else f"used {actual} {self.count} against a budget of {budget}",
            metadata={"actual": actual, "budget": budget, "count": self.count},
        )


@SCORERS.register("trajectory_loop_detection", aliases=("trajectory-loop-detection",))
class TrajectoryLoopDetectionScorer(_TrajectoryScorer):
    """Fails when the same call repeats more than a configured number of times.

    Counts *consecutive* repeats by default, which is what a stuck agent looks like.
    Set ``consecutive=False`` to count total repeats instead, catching an agent that
    revisits the same call throughout rather than in one run.
    """

    default_name = "trajectory_loop_detection"
    requires_reference = False

    def __init__(self, name: str | None = None, max_repeats: int = 2, consecutive: bool = True, **kwargs: Any):
        super().__init__(name, **kwargs)
        if max_repeats < 1:
            raise ValueError(f"max_repeats must be >= 1; got {max_repeats}")
        self.max_repeats = max_repeats
        self.consecutive = consecutive

    def _score_quality(self, item: EvalItem, trajectory: AgentTrajectory) -> ScoreResult:
        calls = self._candidate_calls(trajectory)
        worst, worst_name = self._worst_repeat(calls)
        looped = worst > self.max_repeats
        return ScoreResult(
            self.name,
            value=0.0 if looped else 1.0,
            passed=not looped,
            comment=(f"'{worst_name}' repeated {worst} times (max {self.max_repeats})" if looped else None),
            metadata={"max_observed_repeats": worst, "max_repeats": self.max_repeats},
        )

    def _worst_repeat(self, calls: tuple[CanonicalCall, ...]) -> tuple[int, str]:
        """The highest repeat count observed, and the tool name that produced it."""
        if not calls:
            return (0, "")
        if not self.consecutive:
            call, count = Counter(calls).most_common(1)[0]
            return (count, call[0])
        best_count, best_call = 1, calls[0]
        run_count = 1
        for previous, current in pairwise(calls):
            run_count = run_count + 1 if current == previous else 1
            if run_count > best_count:
                best_count, best_call = run_count, current
        return (best_count, best_call[0])


@SCORERS.register("trajectory_recovery", aliases=("trajectory-recovery",))
class TrajectoryRecoveryScorer(_TrajectoryScorer):
    """Fails an agent that sails past a failed tool call as though it had succeeded.

    A ``tool_error`` step is acceptable — tools fail. What is not acceptable is
    treating the failure as a success. After an error the agent must either retry the
    same tool, call a different one, or stop without claiming success.

    'Claiming success' is read from the final step: a ``final`` step is treated as a
    success claim unless its metadata marks it otherwise via ``failure_key``.
    """

    default_name = "trajectory_recovery"
    requires_reference = False

    def __init__(self, name: str | None = None, failure_key: str = "failed", **kwargs: Any):
        super().__init__(name, **kwargs)
        self.failure_key = failure_key

    def _score_quality(self, item: EvalItem, trajectory: AgentTrajectory) -> ScoreResult:
        steps = trajectory.steps
        unrecovered: list[str] = []
        for index, step in enumerate(steps):
            if step.kind != "tool_error":
                continue
            following = steps[index + 1 :]
            acted_again = any(later.kind == "tool_call" for later in following)
            claimed_success = any(
                later.kind == "final" and not later.metadata.get(self.failure_key, False) for later in following
            )
            if not acted_again and claimed_success:
                unrecovered.append(step.tool_call.name if step.tool_call is not None else "<unknown tool>")
        if not unrecovered:
            return ScoreResult(
                self.name,
                value=1.0,
                passed=True,
                comment=None,
                metadata={"tool_errors": sum(1 for s in steps if s.kind == "tool_error")},
            )
        return ScoreResult(
            self.name,
            value=0.0,
            passed=False,
            comment=f"claimed success after unrecovered tool error(s): {unrecovered}",
            metadata={"unrecovered_tools": unrecovered},
        )
