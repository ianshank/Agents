"""Did the suite run at all, and does it stay quiet on correct code?

Two scorers, kept together because both read the reference run and neither reads a mutant.
``test_executability`` is the deterministic gate the other three depend on;
``testgen_green_on_correct`` is the false-alarm measure the spec insists is never blended
into fault detection.
"""

from __future__ import annotations

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import NO_EVIDENCE, NOT_EXECUTABLE, evidence_metadata, is_executable, not_applicable, read_evidence


@SCORERS.register("test_executability")
class TestExecutabilityScorer(Scorer):
    """Is the generated suite collectable and runnable at all?

    Measured before anything else and reported separately from any measure of quality: a
    mutation score over a suite that never ran is not a low score, it is a meaningless one.

    A suite that collects **zero** tests fails. It is the case most easily mistaken for a
    pass — nothing raised, no test failed — and treating "no tests" as success would let an
    empty file score perfectly on every other measure that depends on this one.
    """

    default_name = "test_executability"

    def __init__(self, name: str | None = None, on_missing: float = 0.0) -> None:
        super().__init__(name)
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evidence = read_evidence(output)
        if evidence is None:
            return not_applicable(self.name, NO_EVIDENCE, self.on_missing)
        runnable = is_executable(evidence)
        collection_error = evidence.get("collection_error")
        comment = str(collection_error) if collection_error else None
        if not runnable and not collection_error:
            comment = "suite collected zero tests"
        return ScoreResult(
            self.name,
            value=1.0 if runnable else 0.0,
            passed=runnable,
            comment=comment,
            metadata=evidence_metadata(evidence, collection_error=collection_error),
        )


@SCORERS.register("testgen_green_on_correct")
class TestgenGreenOnCorrectScorer(Scorer):
    """What fraction of the suite's tests fail against the KNOWN-CORRECT implementation?

    Reported as a rate where **lower is better**, so a gate rule bounds it with ``max``
    rather than ``min``. Emitted as its own score and never folded into
    ``testgen_mutation_score``: a suite that fails on correct code is worse than useless —
    it costs review time on every run and trains the team to ignore it — and a single
    blended quality number lets a high mutation score hide exactly that.
    """

    default_name = "testgen_green_on_correct"

    def __init__(self, name: str | None = None, max_false_alarm_rate: float = 0.0, on_missing: float = 1.0) -> None:
        super().__init__(name)
        self.max_false_alarm_rate = float(max_false_alarm_rate)
        # Defaults to 1.0, not 0.0: this scorer's scale is inverted, so the value that
        # means "no information" must be the BAD end. A 0.0 here would read as a perfect
        # false-alarm rate and quietly improve the mean of a run that measured nothing.
        self.on_missing = float(on_missing)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        evidence = read_evidence(output)
        if evidence is None:
            return not_applicable(self.name, NO_EVIDENCE, self.on_missing)
        if not is_executable(evidence):
            return not_applicable(self.name, NOT_EXECUTABLE, self.on_missing)

        green = evidence.get("green_on_correct") or {}
        ran = int(green.get("ran") or 0)
        failed = int(green.get("failed") or 0)
        rate = failed / ran if ran else 0.0
        passed = rate <= self.max_false_alarm_rate
        return ScoreResult(
            self.name,
            value=rate,
            passed=passed,
            comment=f"{failed}/{ran} test(s) failed against the correct implementation",
            metadata=evidence_metadata(
                evidence,
                false_alarms=failed,
                tests_run=ran,
                max_false_alarm_rate=self.max_false_alarm_rate,
            ),
        )
