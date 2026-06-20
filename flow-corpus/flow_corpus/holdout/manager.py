"""Stratified holdout with a SINGLE split authority.

Two holdouts, reported separately and never merged:

* **instance-holdout** (primary): pool the *seen* flow types and measure Brier
  reliability on an unseen partition of *instances* (tasks). This is the honest
  calibration number — same flow shapes, unseen tasks.
* **type-holdout** (generalization, caveated): hold out an entire flow *type* and
  measure reliability on it. Because a recalibrator fit on the seen types would
  clamp (extrapolate) outside its fitted confidence support, we also report the
  fraction of held-out-type confidences that fall outside that support.

The manager owns the instance partition (via ``agent_core.golden._bucket``) and is
the *only* place a split happens — the model builder must not re-split, or the two
folds would compound and shrink the already-scarce per-unit samples (defect M4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from flow_corpus.config import CorpusConfig
from flow_corpus.partition import bucket
from flow_corpus.validation.reliability import ReliabilityReport, brier_reliability

if TYPE_CHECKING:
    from flow_corpus.validation.runner import RunResult


@dataclass(frozen=True)
class Sample:
    instance_id: str
    confidence: float
    outcome: int


@dataclass(frozen=True)
class HoldoutReport:
    instance_holdout: ReliabilityReport  # primary calibration number
    type_holdout: ReliabilityReport  # generalization to an unseen flow type
    held_out_type: str
    extrapolation_fraction: float  # held-out confidences outside the seen support
    seen_support: tuple[float, float] | None  # (min, max) confidence over seen types


def samples_from_run(run: RunResult) -> list[Sample]:
    """Extract confidence-bearing, determinate samples from a RunResult."""
    verdict_by_id = {o.instance_id: o.verdict for o in run.oracle_results}
    out: list[Sample] = []
    for fr in run.flow_results:
        verdict = verdict_by_id.get(fr.instance_id)
        if verdict is None or fr.raw_confidence is None:
            continue
        out.append(
            Sample(
                instance_id=fr.instance_id,
                confidence=fr.raw_confidence,
                outcome=1 if verdict else 0,
            )
        )
    return out


class HoldoutManager:
    def __init__(self, cfg: CorpusConfig, *, seed: int = 0) -> None:
        self.cfg = cfg
        self.seed = seed

    def _measured_instances(self, samples: Sequence[Sample]) -> list[Sample]:
        """The held-out (unseen-task) partition of *samples*, owned solely here."""
        edge = self.cfg.holdout_fit_fraction
        return [s for s in samples if bucket(self.seed, s.instance_id) >= edge]

    def evaluate(
        self,
        samples_by_type: Mapping[str, Sequence[Sample]],
        held_out_type: str,
    ) -> HoldoutReport:
        if held_out_type not in samples_by_type:
            raise ValueError(f"held_out_type {held_out_type!r} not present in samples_by_type")

        seen: list[Sample] = [
            s for t, samples in samples_by_type.items() if t != held_out_type for s in samples
        ]
        held: list[Sample] = list(samples_by_type[held_out_type])

        # instance-holdout (primary): unseen TASKS within the SEEN flow types.
        measured = self._measured_instances(seen)
        instance_report = brier_reliability(
            [s.confidence for s in measured], [s.outcome for s in measured], self.cfg
        )

        # type-holdout (generalization): the entire unseen flow type.
        type_report = brier_reliability(
            [s.confidence for s in held], [s.outcome for s in held], self.cfg
        )

        # Extrapolation caveat: how much of the held-out type sits outside the
        # confidence support a recalibrator fit on the seen types would have seen.
        support: tuple[float, float] | None = None
        extrapolation = 0.0
        if seen and held:
            lo = min(s.confidence for s in seen)
            hi = max(s.confidence for s in seen)
            support = (lo, hi)
            outside = sum(1 for s in held if s.confidence < lo or s.confidence > hi)
            extrapolation = outside / len(held)

        return HoldoutReport(
            instance_holdout=instance_report,
            type_holdout=type_report,
            held_out_type=held_out_type,
            extrapolation_fraction=extrapolation,
            seen_support=support,
        )
