"""Onset-tolerance and abstention scorers (synthetic RCA scope).

Implements ``openspec/changes/add-rca-eval-matrix`` tasks 4.4-4.6: the scorers that
measure the failure mode this task family actually exhibits — confident diagnosis on
insufficient evidence. Pure, deterministic, no judge, no I/O.

Timezone discipline is a spec requirement, not a convention: both instants are
normalised to UTC before comparison, a claimed onset without an offset is malformed
(never interpreted in an implicit local zone), and a wall-clock match in the wrong
declared zone scores outside tolerance.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import NO_CANDIDATES, UNANSWERABLE, is_unanswerable, not_applicable, read_candidates, read_correct, read_ranking

logger = logging.getLogger(__name__)

NO_ONSET = "item declares no confirmed onset"
NO_CLAIMED_ONSET = "the diagnosis claims no onset"
MALFORMED_ONSET = "an onset timestamp is malformed or carries no offset"


def _parse_instant(raw: Any) -> datetime | None:
    """Parse an ISO-8601 instant REQUIRING an explicit offset; None when absent/invalid.

    A timestamp without an offset is refused rather than interpreted in the local zone:
    the spec forbids implicit-timezone comparison outright (the reference benchmark's
    leading spurious-mismatch cause).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def read_claimed_onset(output: TargetOutput) -> datetime | None | str:
    """The diagnosis's claimed onset instant, or a sentinel string for the absent cases.

    Returns the parsed instant, ``"absent"`` when the output claims no onset (an
    abstention or a ranking-only answer), and ``None`` when a claim is present but
    malformed (including a missing offset).
    """
    raw: Any = output.output
    if not isinstance(raw, dict):
        return "absent"
    if raw.get("abstain") is True or raw.get("insufficient_evidence") is True:
        return "absent"
    claim = raw.get("onset")
    if claim is None:
        return "absent"
    parsed = _parse_instant(claim)
    return parsed if parsed is not None else None


@SCORERS.register("rca_onset_within_tolerance", aliases=("rca-onset-within-tolerance",))
class RcaOnsetWithinToleranceScorer(Scorer):
    """Whether the claimed onset falls within ``tolerance_seconds`` of the confirmed one.

    Both instants are normalised to UTC before comparison; the evidence records both
    normalised readings so a timezone-shifted answer is visibly wrong, not silently
    right. On an unanswerable item (no confirmed onset) reports ``passed=None``.
    """

    default_name = "rca_onset_within_tolerance"

    def __init__(self, name: str | None = None, tolerance_seconds: float = 900.0) -> None:
        super().__init__(name)
        if tolerance_seconds <= 0:
            raise ValueError(f"tolerance_seconds must be > 0, got {tolerance_seconds!r}")
        self.tolerance_seconds = float(tolerance_seconds)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        correct = read_correct(item)
        if correct is not None and is_unanswerable(correct):
            return not_applicable(self.name, UNANSWERABLE)
        onset_raw = item.inputs.get("onset") if isinstance(item.inputs, dict) else None
        confirmed = _parse_instant(onset_raw)
        if confirmed is None:
            return not_applicable(self.name, NO_ONSET if onset_raw is None else MALFORMED_ONSET)
        claimed = read_claimed_onset(output)
        if isinstance(claimed, str):  # the "absent" sentinel
            return not_applicable(self.name, NO_CLAIMED_ONSET)
        if claimed is None:
            return ScoreResult(
                self.name,
                value=0.0,
                passed=False,
                comment="claimed onset is malformed or carries no offset",
                metadata={"confirmed_onset_utc": confirmed.astimezone(UTC).isoformat()},
            )
        delta = abs((claimed - confirmed).total_seconds())
        within = delta <= self.tolerance_seconds
        return ScoreResult(
            self.name,
            value=1.0 if within else 0.0,
            passed=within,
            comment=f"|delta|={delta:.0f}s vs tolerance {self.tolerance_seconds:.0f}s",
            metadata={
                # Normalised to UTC so the field names tell the truth: a shifted claim
                # is visibly wrong in the evidence, not merely scored wrong.
                "confirmed_onset_utc": confirmed.astimezone(UTC).isoformat(),
                "claimed_onset_utc": claimed.astimezone(UTC).isoformat(),
                "delta_seconds": delta,
                "tolerance_seconds": self.tolerance_seconds,
            },
        )


@SCORERS.register("rca_abstention_correctness", aliases=("rca-abstention-correctness",))
class RcaAbstentionCorrectnessScorer(Scorer):
    """Whether the agent declined exactly when the item is unanswerable.

    Declining on an unanswerable item is correct; naming a cause on one is incorrect;
    declining on an answerable item is incorrect (not free). This is the scorer that
    separates "I don't know" from a wrong guess — the failure mode the reference
    replications measure as dominant.
    """

    default_name = "rca_abstention_correctness"

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
        ranking = read_ranking(output)
        if ranking is None:
            return not_applicable(self.name, "ranked diagnosis is malformed", self.on_missing)
        declined = not ranking
        answerable = not is_unanswerable(correct)
        correct_abstention = declined != answerable  # declined iff unanswerable
        if correct_abstention:
            disposition = "correct_abstention" if declined else "answered_answerable"
        else:
            disposition = "false_answer" if answerable is False else "missed_abstention"
        return ScoreResult(
            self.name,
            value=1.0 if correct_abstention else 0.0,
            passed=correct_abstention,
            comment=f"{disposition} (answerable={answerable}, declined={declined})",
            metadata={
                "answerable": answerable,
                "declined": declined,
                "disposition": disposition,
            },
        )


@SCORERS.register("rca_false_accusation_rate", aliases=("rca-false-accusation-rate",))
class RcaFalseAccusationRateScorer(Scorer):
    """1.0 when the agent names a cause on an unanswerable item, else 0.0.

    The corpus-wide mean reads as the false-accusation rate; ``pass_rate`` reads as the
    clean-decline rate over unanswerable items only (answerable items are
    ``passed=None`` — a false accusation is only defined where no cause exists).
    """

    default_name = "rca_false_accusation_rate"

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
        if not is_unanswerable(correct):
            return not_applicable(self.name, "answerable item; false accusation is not defined", 0.0)
        ranking = read_ranking(output)
        if ranking is None:
            return not_applicable(self.name, "ranked diagnosis is malformed", self.on_missing)
        accused = bool(ranking)
        return ScoreResult(
            self.name,
            value=1.0 if accused else 0.0,
            passed=not accused,
            comment=("named a cause on an unanswerable item" if accused else "declined on an unanswerable item"),
            metadata={"accused": accused, "named": list(ranking)},
        )
