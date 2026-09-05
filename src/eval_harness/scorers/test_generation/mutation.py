"""Did the suite detect seeded faults, and did it cover the obligations it was asked to?

Two scorers over the mutant run. Both depend on ``test_executability`` having passed —
a mutation score over a suite that never ran is meaningless, not low.
"""

from __future__ import annotations

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import NO_EVIDENCE, NOT_EXECUTABLE, evidence_metadata, is_executable, not_applicable, read_evidence

#: The two denominators, named rather than implied.
#:
#: ``raw`` divides by every non-equivalent mutant seeded for the focal method — "how much
#: of the seeded fault space did this suite catch". ``normalized`` divides by the
#: non-equivalent mutants the suite actually *reached* — "of what it reached, how much did
#: it kill". A suite can look strong on one while being weak on the other, which is why the
#: spec forbids reporting either alone.
#:
#: Attribution, corrected during this change's review: the *normalized* denominator is
#: Inozemtseva & Holmes (ICSE 2014), where it is a "normalized effectiveness measurement".
#: The focal-method *raw* denominator is NOT theirs — theirs is project-wide — it is the
#: ISSTA 2026 replication study's adaptation. Do not attribute the focal-method form to
#: Inozemtseva.
DENOMINATORS = ("raw", "normalized")


@SCORERS.register("testgen_mutation_score")
class TestgenMutationScoreScorer(Scorer):
    """What fraction of seeded faults did the suite kill?

    Emits **both** denominators on every verdict, each labelled with the counts it was
    computed from, so a reader can recompute either and this scorer does not have to be
    trusted about which one it used. ``denominator`` selects which becomes the headline
    value; the other is still emitted.

    Equivalent mutants are excluded from both, and the count excluded is emitted — an
    equivalent mutant cannot be killed by any suite, so counting one would cap the score
    below 1.0 for reasons that have nothing to do with the suite under test.
    """

    default_name = "testgen_mutation_score"

    def __init__(self, name: str | None = None, denominator: str = "raw", on_missing: float = 0.0) -> None:
        super().__init__(name)
        if denominator not in DENOMINATORS:
            raise ValueError(f"denominator must be one of {DENOMINATORS}, got {denominator!r}")
        self.denominator = denominator
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evidence = read_evidence(output)
        if evidence is None:
            return not_applicable(self.name, NO_EVIDENCE, self.on_missing)
        if not is_executable(evidence):
            return not_applicable(self.name, NOT_EXECUTABLE, self.on_missing)

        mutants = evidence.get("mutants") or {}
        generated = int(mutants.get("generated") or 0)
        covered = int(mutants.get("covered") or 0)
        killed = int(mutants.get("killed") or 0)
        excluded = int(mutants.get("equivalent_excluded") or 0)
        if generated == 0:
            # No non-equivalent mutant to detect: the item cannot discriminate, and a 0.0
            # here would blame the suite for the corpus.
            return not_applicable(self.name, "no non-equivalent mutants for this item", self.on_missing)

        figures = {
            "raw": killed / generated,
            "normalized": (killed / covered) if covered else 0.0,
        }
        value = figures[self.denominator]
        return ScoreResult(
            self.name,
            value=value,
            passed=None if covered == 0 and self.denominator == "normalized" else value > 0.0,
            comment=(
                f"raw {killed}/{generated} (all non-equivalent), "
                f"normalized {killed}/{covered} (covered only), "
                f"{excluded} equivalent excluded"
            ),
            metadata=evidence_metadata(
                evidence,
                headline_denominator=self.denominator,
                raw=figures["raw"],
                raw_denominator="non_equivalent_generated",
                raw_denominator_count=generated,
                normalized=figures["normalized"],
                normalized_denominator="non_equivalent_covered",
                normalized_denominator_count=covered,
                killed=killed,
                equivalent_excluded=excluded,
            ),
        )


@SCORERS.register("requirement_obligation_recall")
class RequirementObligationRecallScorer(Scorer):
    """What fraction of the item's DECLARED gold obligations did the suite cover?

    The gold set is carried by the corpus item, never inferred from the generated tests.
    Inferring the target from the artifact being scored is circular: a suite would define
    its own obligations and always score highly.

    An item declaring no obligations is not-applicable rather than a perfect or a zero
    score — both would be claims about a suite that nothing was asked of.
    """

    default_name = "requirement_obligation_recall"

    def __init__(self, name: str | None = None, on_missing: float = 0.0) -> None:
        super().__init__(name)
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evidence = read_evidence(output)
        if evidence is None:
            return not_applicable(self.name, NO_EVIDENCE, self.on_missing)
        if not is_executable(evidence):
            return not_applicable(self.name, NOT_EXECUTABLE, self.on_missing)

        declared = list(evidence.get("obligations_declared") or [])
        if not declared:
            return not_applicable(self.name, "item declares no gold obligations", self.on_missing)
        covered = [ob for ob in evidence.get("obligations_covered") or [] if ob in declared]
        recall = len(covered) / len(declared)
        return ScoreResult(
            self.name,
            value=recall,
            passed=recall > 0.0,
            comment=f"{len(covered)}/{len(declared)} declared obligation(s) covered",
            metadata=evidence_metadata(
                evidence,
                obligations_declared=len(declared),
                obligations_covered=len(covered),
                uncovered=sorted(set(declared) - set(covered)),
            ),
        )
