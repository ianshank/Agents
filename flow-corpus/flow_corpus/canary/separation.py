"""Canary separation margin — Wilson-bounded pass-rate gap (NOT AUROC).

The canary asks: does a gold agent land clearly above a no-op? We measure the gap
between the gold agent's pass-rate Wilson *lower* bound and the no-op's pass-rate
Wilson *upper* bound. Using bounds (not point estimates) makes the margin honest at
small N.

Why not AUROC: ``agent_core.calibration.auroc`` is undefined for a single class, and
the no-op is single-class by construction (it passes nothing). A pass-rate gap is
well-defined for any outcomes, including all-0 / all-1 slices.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.calibration import wilson_interval

from flow_corpus.config import CorpusConfig


@dataclass(frozen=True)
class SeparationReport:
    gold_rate: float
    gold_ci_low: float
    baseline_rate: float
    baseline_ci_high: float
    margin: float  # gold_ci_low - baseline_ci_high (may be negative)
    separated: bool  # margin >= cfg.min_canary_margin

    @property
    def passes(self) -> bool:
        return self.separated


def _rate_and_ci(outcomes: Sequence[int], z: float) -> tuple[float, float, float]:
    n = len(outcomes)
    if n == 0:
        raise ValueError("cannot compute separation on empty outcomes")
    k = sum(outcomes)
    low, high = wilson_interval(k, n, z)
    return k / n, low, high


def canary_separation(
    gold_outcomes: Sequence[int],
    baseline_outcomes: Sequence[int],
    cfg: CorpusConfig,
) -> SeparationReport:
    """Return the gold-vs-baseline separation report.

    ``baseline_outcomes`` is typically the no-op (or random) agent's per-instance
    correctness (1/0). The margin is the gold lower bound minus the baseline upper
    bound — positive and large means the corpus discriminates.
    """
    gold_rate, gold_low, _ = _rate_and_ci(gold_outcomes, cfg.wilson_z)
    base_rate, _, base_high = _rate_and_ci(baseline_outcomes, cfg.wilson_z)
    margin = gold_low - base_high
    return SeparationReport(
        gold_rate=gold_rate,
        gold_ci_low=gold_low,
        baseline_rate=base_rate,
        baseline_ci_high=base_high,
        margin=margin,
        separated=margin >= cfg.min_canary_margin,
    )
