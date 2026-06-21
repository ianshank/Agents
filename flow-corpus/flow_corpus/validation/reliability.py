"""Brier reliability — the primary calibration gate + stability metric.

The harness's ``CalibrationReport`` / ``evaluate_on_split`` expose only the *scalar*
Brier, not its Murphy decomposition. The primary metric here is the **reliability
term** of that decomposition (a proper-scoring calibration measure, far less
binning-artefact-prone than ECE), so we call ``brier_decomposition`` directly rather
than routing through ``evaluate_calibration``.

Power rule (spec): a reliability number on fewer than ``power_min_sample`` resolved,
confidence-bearing outcomes is *directional only* and cannot gate a phase.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.calibration import brier_decomposition

from flow_corpus.config import CorpusConfig

from .power import is_directional_only


@dataclass(frozen=True)
class ReliabilityReport:
    reliability: float | None  # None when no confidence-bearing outcomes exist
    resolution: float | None
    n: int
    directional_only: bool  # True when n < power_min_sample (cannot gate)
    may_gate: bool  # not directional AND reliability <= max_brier_reliability

    @property
    def passes(self) -> bool:
        return self.may_gate


def brier_reliability(
    confidences: Sequence[float],
    outcomes: Sequence[int],
    cfg: CorpusConfig,
) -> ReliabilityReport:
    """Compute the Brier reliability term over (confidence, outcome) pairs.

    Callers must pass only confidence-bearing, *determinate* outcomes — indeterminate
    oracle verdicts are never fed here (the gate is given no guesses).
    """
    if len(confidences) != len(outcomes):
        raise ValueError("confidences and outcomes must be of equal length")
    n = len(confidences)
    if n == 0:
        return ReliabilityReport(None, None, 0, directional_only=True, may_gate=False)

    decomp = brier_decomposition(confidences, outcomes, cfg.n_bins)
    directional = is_directional_only(n, cfg.power_min_sample)
    may_gate = (not directional) and decomp.reliability <= cfg.max_brier_reliability
    return ReliabilityReport(
        reliability=decomp.reliability,
        resolution=decomp.resolution,
        n=n,
        directional_only=directional,
        may_gate=may_gate,
    )
