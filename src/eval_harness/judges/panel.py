"""``PanelJudge``: aggregates N member judges into one verdict, honestly.

Split into its own module rather than inlined in ``judges/__init__.py`` purely
to stay under the 500-line hard file budget (``scripts/check_size_budget.py``)
-- the same reason ``scorers/__init__.py`` keeps ``trajectory.py`` as a sibling
module, imported at the bottom for its registration side effect.

A single LLM judge is a single point of *systematic* failure -- order bias,
verbosity preference, self-preference (``extend-judge-calibration``'s own
failure modes). A panel of independent members makes a complementary signal
measurable per item: disagreement. When members score the same output far
apart, that spread is evidence about the judging machinery itself, and the
honest response is to surface it and abstain -- not average it into a
confident-looking number. Mirrors the house convention everywhere else:
``Decision.CANT_TELL`` in campaigns, ``cant_tell`` in the regression estimate,
``OracleResult.verdict = None`` routing to the audit queue rather than a guess.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES

logger = logging.getLogger(__name__)


@JUDGES.register("panel")
class PanelJudge(Judge):
    """Aggregates member judges' verdicts under an explicit strategy.

    Members are built once at construction via the same registry the engine
    uses (mirrors :class:`~eval_harness.scorers.CompositeScorer`'s registry-
    built-children pattern) -- never re-resolved per call. Evaluated
    *sequentially*, in declaration order: required for the determinism
    guarantee (a thread-pooled fan-out would satisfy every other requirement
    and fail this one intermittently). No alias is registered -- ``panel`` is
    exact-equality asserted in ``FROZEN_ALIAS_MAP``, and a discoverability
    alias earns nothing a registered name doesn't already give.
    """

    _STRATEGIES = ("median", "mean", "majority")

    def __init__(
        self,
        members: list[dict],
        strategy: str = "median",
        member_pass_threshold: float = 0.5,
        disagreement_threshold: float | None = None,
        quorum: int | None = None,
        on_skip: float = 0.0,
    ) -> None:
        if not members:
            raise ValueError("PanelJudge requires at least one member")
        if len(members) == 1:
            raise ValueError(
                "PanelJudge requires at least two members "
                "(a one-member panel's spread is structurally 0 -- a judge with extra cost "
                "and a disabled safety mechanism)"
            )
        if strategy not in self._STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}; supported: {list(self._STRATEGIES)}")

        self._members: list[tuple[str, Judge]] = []
        for idx, spec in enumerate(members):
            if not isinstance(spec, dict):
                raise ValueError(f"each PanelJudge member must be a mapping; got {type(spec).__name__}")
            mtype = spec.get("type")
            if not mtype:
                raise ValueError("each PanelJudge member must specify a 'type'")
            member = JUDGES.create(mtype, spec.get("params", {}))
            label = spec.get("name") or f"{mtype}#{idx}"
            self._members.append((label, member))

        self.strategy = strategy
        self.member_pass_threshold = float(member_pass_threshold)
        self.disagreement_threshold = disagreement_threshold
        self.quorum = quorum if quorum is not None else (len(self._members) // 2 + 1)
        if not 1 <= self.quorum <= len(self._members):
            raise ValueError(
                f"quorum must be between 1 and {len(self._members)} (the configured member "
                f"count, never the survivor count -- a survivor-relative quorum is trivially "
                f"self-satisfying); got {self.quorum}"
            )
        self.on_skip = float(on_skip)
        # Read (duck-typed) by build_budgeted_judge so a budget/rate cap sized for one
        # provider call reserves N. Recursive, not len(members): a member that is itself
        # a panel performs its own N calls, not one, so counting members instead of calls
        # would recreate the exact under-charge this mechanism exists to prevent, one
        # level up (a nested panel is legal -- members are built via JUDGES.create, and
        # "panel" is registered in JUDGES).
        self.calls_per_evaluate = sum(getattr(member, "calls_per_evaluate", 1) for _, member in self._members)

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        per_member: list[dict[str, Any]] = []
        failed_members: list[dict[str, str]] = []
        for name, member in self._members:
            logger.debug("panel: calling member %r (%s)", name, type(member).__name__)
            try:
                verdict = member.evaluate(prompt, context)
                per_member.append({"name": name, "score": verdict.score, "reasoning": verdict.reasoning})
            except Exception as exc:  # a member outage is excluded, never a fabricated 0.0 vote
                logger.warning("panel: member %r failed: %s", name, exc)
                failed_members.append({"name": name, "error": str(exc)})

        # Quorum before spread: with 0 survivors, max()/min() below would raise on an
        # empty sequence, and a survivor-starved panel should abstain, not crash.
        survivors = [m["score"] for m in per_member]
        if len(survivors) < self.quorum:
            reason = f"below quorum: {len(survivors)}/{len(self._members)} members survived, need {self.quorum}"
            logger.warning("panel: %s; abstaining", reason)
            return self._abstain(reason, per_member, failed_members)

        spread = max(survivors) - min(survivors)
        stdev = statistics.pstdev(survivors)
        if self.disagreement_threshold is not None and spread > self.disagreement_threshold:
            reason = f"disagreement {spread:.4f} exceeds threshold {self.disagreement_threshold:.4f}"
            logger.warning("panel: %s; abstaining", reason)
            return self._abstain(reason, per_member, failed_members, spread=spread, stdev=stdev)

        if self.strategy == "median":
            score = statistics.median(survivors)  # even N: mean of the middle two, documented
        elif self.strategy == "mean":
            score = statistics.fmean(survivors)
        else:  # majority: a pass *fraction*, not a score in the members' own space
            score = sum(1 for s in survivors if s >= self.member_pass_threshold) / len(survivors)

        return JudgeVerdict(
            score=score,
            reasoning=f"{self.strategy} of {len(survivors)} member(s), spread={spread:.4f}",
            raw={
                "members": per_member,
                "failed_members": failed_members,
                "spread": spread,
                "stdev": stdev,
                "strategy": self.strategy,
                "abstained": False,
            },
        )

    def _abstain(
        self,
        reason: str,
        per_member: list[dict[str, Any]],
        failed_members: list[dict[str, str]],
        *,
        spread: float | None = None,
        stdev: float | None = None,
    ) -> JudgeVerdict:
        # "on_skip" (not e.g. "abstain_score"): AutoevalsScorer already established this
        # name for "the value recorded when this evaluator declined to score" -- a second
        # name for one concept is how two vocabularies start.
        return JudgeVerdict(
            score=self.on_skip,
            reasoning=reason,
            raw={
                "members": per_member,
                "failed_members": failed_members,
                "spread": spread,
                "stdev": stdev,
                "strategy": self.strategy,
                "abstained": True,
            },
        )

    def attach_client(self, client: Any) -> None:
        """Forward the traced client to every member that accepts it.

        Duck-typed, optional hook -- not on the ``Judge`` Protocol. Without this
        fan-out, tracing would silently die for members while the panel itself
        appeared traced (it *is* the top-level ``judge`` object the engine calls
        this on).
        """
        for _, member in self._members:
            attach = getattr(member, "attach_client", None)
            if callable(attach):
                attach(client)
