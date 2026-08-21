"""State-outcome scorers.

Both read the ``StateEvaluation`` the engine attaches to ``ctx.extra`` when a
``StateAdapter`` is configured (``core/_state_lifecycle.py``) — pure over data
the engine already computed, no state comparison or I/O of their own. Split
into its own file rather than grown inside ``scorers/__init__.py`` (precedent:
``scorers/trajectory.py``).

Both report ``passed=None`` ("not applicable") when no evaluation is present:
either no ``state_adapter`` is configured for this run, or the adapter's own
snapshot/evaluate call failed — already visible as a separate
``"state_lifecycle"`` failing score in that case, so these two add no
redundant noise on top of it.
"""

from __future__ import annotations

from ..core.interfaces import Scorer
from ..core.types import EvalItem, RunContext, ScoreResult, StateEvaluation, TargetOutput
from ..plugins import SCORERS


def _read_evaluation(ctx: RunContext) -> StateEvaluation | None:
    evaluation = ctx.extra.get("state_evaluation") if ctx.extra else None
    return evaluation if isinstance(evaluation, StateEvaluation) else None


@SCORERS.register("state_transition")
class StateTransitionScorer(Scorer):
    """Did the observed before/after state transition match the declared goal?

    ``goal_reached`` is the adapter's own verdict (``design.md`` "The adapter
    contract"): whether the item's declared expectation was met, or, absent
    one, whether anything changed at all — this scorer performs no comparison
    of its own, only reads the result.
    """

    default_name = "state_transition"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evaluation = _read_evaluation(ctx)
        if evaluation is None:
            return ScoreResult(self.name, value=0.0, passed=None, comment=None)
        return ScoreResult(
            self.name,
            value=1.0 if evaluation.goal_reached else 0.0,
            passed=evaluation.goal_reached,
            comment=evaluation.reasoning or None,
        )


@SCORERS.register("policy_violation")
class PolicyViolationScorer(Scorer):
    """Did the attempt violate a declared state policy, independent of goal success?

    Fails independently of whether the goal was reached (``design.md`` "What
    changes") — an attempt that reaches its goal via a forbidden mutation
    (``goal_reached=True``, ``policy_violated=True``) still fails this scorer,
    the exact scenario ``tasks.md`` names explicitly.
    """

    default_name = "policy_violation"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evaluation = _read_evaluation(ctx)
        if evaluation is None:
            return ScoreResult(self.name, value=0.0, passed=None, comment=None)
        passed = not evaluation.policy_violated
        return ScoreResult(
            self.name,
            value=1.0 if passed else 0.0,
            passed=passed,
            comment=evaluation.reasoning or None,
        )
