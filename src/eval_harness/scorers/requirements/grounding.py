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
    NO_CLAIMS,
    NO_GOLD,
    NO_REQUIREMENTS,
    contradicted_claims,
    not_applicable,
    read_declared_tests,
    read_gold,
    read_recorded_source_ids,
    read_requirements,
    read_source_claims,
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

    Support is checked at two depths, because a citation is not an entailment:

    1. The requirement's ``evidence_links`` must name at least one source the provenance
       wrapper actually recorded. A citation of something never retrieved supports nothing.
    2. When the requirement declares a ``claim`` key, one of those recorded-and-cited
       sources must *assert* that key (``supports``). This is what catches the spec's
       unsupported-constraint scenario: a latency budget asserted against a source whose
       claims say nothing about latency is counted, even though the citation resolves.

    A requirement whose claim some *other* recorded source denies (``refutes``) is a
    silent pick between contradictory sources. It is reported in
    ``contradiction_citations`` and denied a clean pass, but it is not counted toward the
    hallucination rate — the claim is in the evidence; the evidence disagrees with itself.

    A corpus that declares no claim keys falls back to depth 1 alone, so citation-only
    datasets keep scoring as before.
    """

    default_name = "req_scope_hallucination"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        if not reqs:
            return not_applicable(self.name, "the generated set is empty")
        recorded = read_recorded_source_ids(output)
        claims = read_source_claims(item)
        contradicted = contradicted_claims(claims, recorded)
        unsupported: list[str] = []
        contradiction_citations: list[str] = []
        for index, req in enumerate(reqs):
            rid = str(req.get("id", f"req-{index}"))
            cited = [link for link in _links(req, "evidence_links") if link in recorded]
            if not cited:
                logger.debug("Requirement %s has no valid evidence links in recorded sources", rid)
                unsupported.append(rid)
                continue
            claim = req.get("claim")
            if claim is None:
                continue
            claim = str(claim)
            if not any(claim in claims.get(sid, NO_CLAIMS).supports for sid in cited):
                logger.debug("Requirement %s asserts %r, which no cited source supports", rid, claim)
                unsupported.append(rid)
                continue
            if claim in contradicted:
                logger.debug("Requirement %s asserts %r, which another recorded source refutes", rid, claim)
                contradiction_citations.append(rid)
        rate = len(unsupported) / len(reqs)
        contradictory = sorted(set(contradiction_citations))
        return ScoreResult(
            self.name,
            value=rate,
            # A contradiction is not a hallucination, so it stays out of `rate` — but the
            # spec forbids reporting such a requirement as *cleanly* supported, so it
            # still denies the pass.
            passed=not unsupported and not contradictory,
            comment=f"{len(unsupported)}/{len(reqs)} requirements unsupported by recorded evidence"
            + (f"; {len(contradictory)} cite a contradicted claim" if contradictory else ""),
            metadata={
                "unsupported": unsupported,
                "contradiction_citations": contradictory,
                "contradicted_claims": sorted(contradicted),
                "recorded_sources": sorted(recorded),
                "requirement_count": len(reqs),
            },
        )


@SCORERS.register("req_traceability_closure", aliases=("req-traceability-closure",))
class ReqTraceabilityClosureScorer(Scorer):
    """Fraction of requirements with a complete declared chain: AC link, and — where the
    corpus declares tests — a test link referencing a declared test.

    A fluent narrative asserting a link does not satisfy it: only the structured
    ``covers`` / ``test_links`` fields count. A link naming something the corpus does not
    declare breaks the chain on *both* sides — an unknown test, and (where the corpus
    declares a gold set) an acceptance criterion that is not in it. Accepting any
    non-empty ``covers`` would let ``covers: ["anything"]`` close the chain, which is the
    cheapest possible way to score this metric without doing the work.
    """

    default_name = "req_traceability_closure"

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        if not reqs:
            return not_applicable(self.name, "the generated set is empty")
        declared_tests = read_declared_tests(item)
        gold = read_gold(item)
        incomplete: list[str] = []
        for index, req in enumerate(reqs):
            rid = str(req.get("id", f"req-{index}"))
            covers = _links(req, "covers")
            if not covers or (gold is not None and not any(ac in gold for ac in covers)):
                logger.debug("Requirement %s has incomplete traceability: no declared 'covers' link (%s)", rid, covers)
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
