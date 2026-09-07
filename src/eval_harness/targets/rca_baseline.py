"""Deterministic `max-|Z|` baseline target for root-cause diagnosis (synthetic scope).

Implements ``openspec/changes/add-rca-eval-matrix`` task 3. The baseline ranks each
candidate by the largest absolute z-score its telemetry shows across the onset boundary
(post-window mean vs pre-window spread, per metric). It is a **target**, not a scorer:
it produces a diagnosis, and the five RCA scorers grade it on the identical path as any
agent — that is what makes it an honest floor rather than a number imported from a
leaderboard.

Deterministic by construction: no clock, no RNG, no network. ``is_deterministic``
declares it, so ``repetitions > 1`` reports the (uninformative) constant distribution
instead of pretending to measure variance.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from ..core.interfaces import TargetRunner
from ..core.types import EvalItem, TargetOutput
from ..plugins import TARGETS

logger = logging.getLogger(__name__)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    """Population standard deviation; 0.0 for a constant or empty window."""
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / len(values))


def _max_abs_z(metrics: dict[str, Any]) -> float:
    """Largest |z| over a candidate's metrics: post-window mean vs pre-window spread.

    A metric with a constant pre-window (zero spread) is skipped rather than producing
    an infinite z — an infinite z would win every ranking regardless of the post window.
    """
    best = 0.0
    for series in metrics.values():
        if not isinstance(series, dict):
            continue
        pre = [float(v) for v in series.get("pre") or []]
        post = [float(v) for v in series.get("post") or []]
        if not pre or not post:
            continue
        spread = _std(pre)
        if spread <= 0.0:
            continue
        z = abs(_mean(post) - _mean(pre)) / spread
        best = max(best, z)
    return best


@TARGETS.register("rca_maxz", aliases=("rca-maxz",))
class RcaMaxZBaselineTarget(TargetRunner):
    """Rank candidates by largest absolute z-score across the onset boundary.

    Abstains (``{"abstain": True}``) when no candidate's max |z| reaches
    ``z_floor`` — the corpus's unanswerable items exist to measure exactly this
    decline, and a baseline that always guesses would corrupt the abstention
    metrics it is meant to be scored by.
    """

    def __init__(self, z_floor: float = 2.0) -> None:
        if not math.isfinite(z_floor) or z_floor < 0:
            raise ValueError(f"z_floor must be finite and >= 0, got {z_floor!r}")
        self.z_floor = float(z_floor)

    def is_deterministic(self) -> bool:
        return True

    def run(self, item: EvalItem) -> TargetOutput:
        telemetry = item.inputs.get("telemetry") if isinstance(item.inputs, dict) else None
        metrics = telemetry.get("metrics") if isinstance(telemetry, dict) else None
        candidates = item.inputs.get("candidates") if isinstance(item.inputs, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return TargetOutput(output=None, error="item is missing inputs.candidates")
        if not isinstance(metrics, dict) or not metrics:
            return TargetOutput(output=None, error="item is missing inputs.telemetry.metrics")

        scores = {str(svc): _max_abs_z(metrics.get(svc, {})) for svc in candidates}
        ranked = sorted(scores, key=lambda svc: (-scores[svc], svc))  # tie-break by id: deterministic
        if not ranked or scores[ranked[0]] < self.z_floor:
            return TargetOutput(
                output={"abstain": True},
                metadata={"max_abs_z": scores, "z_floor": self.z_floor},
            )
        return TargetOutput(
            output={"ranked": ranked},
            metadata={"max_abs_z": scores, "z_floor": self.z_floor},
        )
