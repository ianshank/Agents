"""Grounding scorers: gold-criteria recall, scope hallucination, traceability closure.

All three read the corpus-declared gold set and the *recorded* evidence (never the
generator's own account), per the spec's anti-circularity and evidence-record rules.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import (
    NO_GOLD,
    NO_REQUIREMENTS,
    not_applicable,
    read_contradictions,
    read_declared_tests,
    read_gold,
    read_recorded_source_ids,
    read_requirements,
)

logger = logging.getLogger(__name__)


def _links(req: dict[str, Any], key: str) -> list[str]:
    raw = req.get(key)
    if not isinstance(raw, list):
        return []
    return [str(v) for v in raw]


@SCORERS.register("req_ac_recall", aliases=("req-ac-recall",))
class ReqAcRecallScorer(Scorer):
    """Covered fraction of the declared gold acceptance-criteria set, in [0, 1].

    A gold criterion is covered when at least one generated requirement declares a
    ``covers`` link to it. The gold set comes from the corpus item — never inferred
    from the generated output.
    """

    default_name = "req_ac_recall"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        gold = read_gold(item)
        if gold is None:
            return not_applicable(self.name, NO_GOLD)
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        if not gold:
            return not_applicable(self.name, "the declared gold set is empty")
        covered = sorted({ac for req in reqs for ac in _links(req, "covers") if ac in gold})
        recall = len(covered) / len(gold)
        return ScoreResult(
            self.name,
            value=recall,
            passed=recall >= 1.0,
            comment=f"{len(covered)}/{len(gold)} gold criteria covered",
            metadata={"covered": covered, "declared": list(gold), "missing": sorted(set(gold) - set(covered))},
        )


@SCORERS.register("req_scope_hallucination", aliases=("req-scope-hallucination",))
class ReqScopeHallucinationScorer(Scorer):
    """Rate of generated requirements unsupported by any recorded evidence item.

    A requirement is supported when its ``evidence_links`` reference at least one source
    the provenance wrapper actually recorded. Citing exactly one side of a declared
    contradiction is reported (``contradiction_citations``), not scored as cleanly
    supported and not silently resolved.
    """

    default_name = "req_scope_hallucination"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        if not reqs:
            return not_applicable(self.name, "the generated set is empty")
        recorded = read_recorded_source_ids(output)
        contradictions = read_contradictions(item)
        unsupported: list[str] = []
        contradiction_citations: list[str] = []
        for index, req in enumerate(reqs):
            links = _links(req, "evidence_links")
            rid = str(req.get("id", f"req-{index}"))
            if not links or not any(link in recorded for link in links):
                logger.debug("Requirement %s has no valid evidence links in recorded sources", rid)
                unsupported.append(rid)
                continue
            for left, right in contradictions:
                cited = set(links)
                if (left in cited) != (right in cited):
                    logger.debug("Requirement %s cites one side of contradiction (%s vs %s)", rid, left, right)
                    contradiction_citations.append(rid)
        rate = len(unsupported) / len(reqs)
        return ScoreResult(
            self.name,
            value=rate,
            passed=not unsupported,
            comment=f"{len(unsupported)}/{len(reqs)} requirements unsupported by recorded evidence",
            metadata={
                "unsupported": unsupported,
                "contradiction_citations": sorted(set(contradiction_citations)),
                "recorded_sources": sorted(recorded),
                "requirement_count": len(reqs),
            },
        )


@SCORERS.register("req_traceability_closure", aliases=("req-traceability-closure",))
class ReqTraceabilityClosureScorer(Scorer):
    """Fraction of requirements with a complete declared chain: AC link, and — where the
    corpus declares tests — a test link referencing a declared test.

    A fluent narrative asserting a link does not satisfy it: only the structured
    ``covers`` / ``test_links`` fields count, and a test link naming a test the corpus
    does not declare breaks the chain.
    """

    default_name = "req_traceability_closure"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        if not reqs:
            return not_applicable(self.name, "the generated set is empty")
        declared_tests = read_declared_tests(item)
        incomplete: list[str] = []
        for index, req in enumerate(reqs):
            rid = str(req.get("id", f"req-{index}"))
            if not _links(req, "covers"):
                logger.debug("Requirement %s has incomplete traceability: missing 'covers' links", rid)
                incomplete.append(rid)
                continue
            if declared_tests is not None:
                test_links = _links(req, "test_links")
                if not test_links or any(link not in declared_tests for link in test_links):
                    logger.debug(
                        "Requirement %s has incomplete traceability: test_links missing or invalid (%s)",
                        rid,
                        test_links,
                    )
                    incomplete.append(rid)
        closure = (len(reqs) - len(incomplete)) / len(reqs)
        return ScoreResult(
            self.name,
            value=closure,
            passed=not incomplete,
            comment=f"{len(reqs) - len(incomplete)}/{len(reqs)} requirements have a complete chain",
            metadata={
                "incomplete": incomplete,
                "declared_tests": declared_tests,
                "requirement_count": len(reqs),
            },
        )
