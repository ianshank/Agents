"""Ranked-diagnosis scorers: AC@k and top-1 component match.

Both are pure over ``(item, output)``. Cut-offs and thresholds live on the scorer /
config, never as literals in the OpenSpec delta.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import (
    DEFAULT_KS,
    MALFORMED_RANKING,
    NO_CANDIDATES,
    NO_RANKING,
    UNANSWERABLE,
    is_unanswerable,
    not_applicable,
    read_candidates,
    read_correct,
    read_ranking,
)

logger = logging.getLogger(__name__)


def _ac_at_k_strict(ranking: list[str], correct: list[str], k: int) -> float:
    """1.0 if any confirmed cause appears in the top-k, else 0.0."""
    if k <= 0 or not correct:
        return 0.0
    top = set(ranking[:k])
    return 1.0 if any(c in top for c in correct) else 0.0


def _ac_at_k_partial(ranking: list[str], correct: list[str], k: int) -> float:
    """Fraction of confirmed causes that appear in the top-k (labelled partial).

    With a singleton correct set this equals strict; with several confirmed causes it
    credits partial retrieval instead of collapsing to a single hit/miss.
    """
    if k <= 0 or not correct:
        return 0.0
    top = set(ranking[:k])
    hits = sum(1 for c in correct if c in top)
    return hits / len(correct)



def _labelled_ac_tables(
    ranking: list[str], correct: list[str], ks: tuple[int, ...]
) -> tuple[dict[str, float], dict[str, float]]:
    """Strict and partial AC@k tables, keys labelled with their cut-off as strings."""
    strict = {str(k): _ac_at_k_strict(ranking, correct, k) for k in ks}
    partial = {str(k): _ac_at_k_partial(ranking, correct, k) for k in ks}
    return strict, partial


@SCORERS.register("rca_ac_at_k", aliases=("rca-ac-at-k",))
class RcaAcAtKScorer(Scorer):
    """Accuracy-at-k over a ranked candidate list vs the item's confirmed cause(s).

    Emits strict and partial figures for every configured ``k``, each labelled with its
    cut-off. The headline ``value`` is **strict** at ``primary_k`` (default 1). An
    unlabelled "accuracy" is never produced.

    On an unanswerable item (empty correct set) reports ``passed=None`` — not zero —
    so abstention metrics own that case (spec: "Correct abstention on an unanswerable
    item").
    """

    default_name = "rca_ac_at_k"

    def __init__(
        self,
        name: str | None = None,
        ks: list[int] | tuple[int, ...] | None = None,
        primary_k: int = 1,
        on_missing: float = 0.0,
    ) -> None:
        super().__init__(name)
        resolved = tuple(int(k) for k in (ks if ks is not None else DEFAULT_KS))
        if not resolved:
            raise ValueError("rca_ac_at_k requires at least one k")
        if any(k < 1 for k in resolved):
            raise ValueError(f"rca_ac_at_k ks must be >= 1, got {resolved!r}")
        self.ks = resolved
        self.primary_k = int(primary_k)
        if self.primary_k not in self.ks:
            raise ValueError(f"primary_k={self.primary_k} is not in ks={self.ks!r}")
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        candidates = read_candidates(item)
        if candidates is None:
            return not_applicable(self.name, NO_CANDIDATES, self.on_missing)
        correct = read_correct(item)
        if correct is None:
            return not_applicable(self.name, "no confirmed cause field on the item", self.on_missing)
        if is_unanswerable(correct):
            return not_applicable(self.name, UNANSWERABLE, self.on_missing)

        ranking = read_ranking(output)
        if ranking is None:
            return not_applicable(self.name, MALFORMED_RANKING, self.on_missing)
        # Empty ranking on an answerable item is a real miss, not not-applicable.
        if not ranking and output.output is None:
            # Truly missing output (no diagnosis published) — distinguish from [].
            return not_applicable(self.name, NO_RANKING, self.on_missing)

        strict_by_k, partial_by_k = _labelled_ac_tables(ranking, correct, self.ks)

        primary_strict = strict_by_k[str(self.primary_k)]
        primary_partial = partial_by_k[str(self.primary_k)]
        outside = [c for c in ranking if c not in candidates]
        comment = (
            f"strict AC@{self.primary_k}={primary_strict:.0f}; "
            f"partial AC@{self.primary_k}={primary_partial:.3f}; "
            f"cut-offs k={list(self.ks)}"
        )
        return ScoreResult(
            self.name,
            value=primary_strict,
            passed=primary_strict >= 1.0,
            comment=comment,
            metadata={
                "mode": "strict",
                "primary_k": self.primary_k,
                "ks": list(self.ks),
                "strict_ac_at_k": strict_by_k,
                "partial_ac_at_k": partial_by_k,
                "ranking": list(ranking),
                "correct": list(correct),
                "candidate_count": len(candidates),
                "outside_candidate_set": outside,
                "outside_candidate_set_count": len(outside),
            },
        )



def _top1_disposition(top1: str, candidates: list[str], correct: list[str]) -> tuple[bool, str, bool, bool]:
    """Return (matched, disposition, outside, in_set_wrong) for a top-1 cause id."""
    outside = top1 not in candidates
    matched = top1 in correct
    if matched:
        disposition = "correct"
    elif outside:
        disposition = "outside_candidate_set"
    else:
        disposition = "in_set_wrong"
    return matched, disposition, outside, disposition == "in_set_wrong"


@SCORERS.register("rca_component_match", aliases=("rca-component-match",))
class RcaComponentMatchScorer(Scorer):
    """Top-1 component against the confirmed cause set.

    An answer outside the declared candidate set is incorrect **and** recorded as
    such in metadata, distinguishably from a wrong in-set choice (spec scenario:
    "A named cause outside the candidate set is not silently discarded").
    """

    default_name = "rca_component_match"

    def __init__(self, name: str | None = None, on_missing: float = 0.0) -> None:
        super().__init__(name)
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        candidates = read_candidates(item)
        if candidates is None:
            return not_applicable(self.name, NO_CANDIDATES, self.on_missing)
        correct = read_correct(item)
        if correct is None:
            return not_applicable(self.name, "no confirmed cause field on the item", self.on_missing)
        if is_unanswerable(correct):
            return not_applicable(self.name, UNANSWERABLE, self.on_missing)

        ranking = read_ranking(output)
        if ranking is None:
            return not_applicable(self.name, MALFORMED_RANKING, self.on_missing)
        if not ranking:
            if output.output is None:
                return not_applicable(self.name, NO_RANKING, self.on_missing)
            return ScoreResult(
                self.name,
                value=0.0,
                passed=False,
                comment="empty ranking; no top-1 component to match",
                metadata={
                    "top1": None,
                    "correct": list(correct),
                    "outside_candidate_set": False,
                    "in_set_wrong": False,
                },
            )

        top1 = ranking[0]
        matched, disposition, outside, in_set_wrong = _top1_disposition(top1, candidates, correct)
        return ScoreResult(
            self.name,
            value=1.0 if matched else 0.0,
            passed=matched,
            comment=f"top-1={top1!r} ({disposition})",
            metadata={
                "top1": top1,
                "correct": list(correct),
                "outside_candidate_set": outside,
                "in_set_wrong": in_set_wrong,
                "disposition": disposition,
            },
        )
