"""Discrimination canary: if the detector can't tell good from bad on cases we
control, nothing downstream means anything.

We synthesise a *known-regression* arm (v2 mean shifted up by ``injected_shift``) and a
*known-null* arm (no shift), run the full generate→judge→detect path on each, and check
that the detector separates them by at least ``min_canary_margin``. Everything is seeded,
so the canary is reproducible and offline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from agent_core.logging_util import get_logger

from .config import BRConfig
from .detector import RegressionDetector
from .generator import PairedResponseGenerator, sycophancy_indicators
from .judge import SyntheticJudge

_log = get_logger("behavioral_regression.canary")


@dataclass(frozen=True)
class CanaryReport:
    regressed_p: float
    null_p: float
    margin: float  # regressed_p - null_p
    separated: bool  # margin >= cfg.min_canary_margin

    @property
    def passes(self) -> bool:
        return self.separated


def _arm_p_regression(cfg: BRConfig, seed: int, v2_shift: float) -> float:
    """Run one canary arm end-to-end and return the detector's p(regression)."""
    gen_rng = random.Random(seed)
    judge_rng = random.Random(seed + 1)
    pairs = PairedResponseGenerator(cfg).generate(gen_rng, v2_shift=v2_shift)
    judge = SyntheticJudge(cfg, judge_rng)
    verdicts = [judge.judge(p) for p in pairs]
    v1_ind, v2_ind = sycophancy_indicators(pairs)
    estimate = RegressionDetector(cfg).detect(
        v1_ind, v2_ind, verdicts, human_labels=None, seed=seed + 2
    )
    _log.debug(
        "canary arm v2_shift=%.4f seed=%d p_regression=%.4f", v2_shift, seed, estimate.p_regression
    )
    return estimate.p_regression


def run_canary(cfg: BRConfig, seed: int) -> CanaryReport:
    """Generate a known-regression and a known-null arm; assert the detector separates
    them. Distinct seeds per arm keep the two draws independent yet reproducible.

    Both arms are built from the *v1 baseline* (v2 mean reset to v1's mean) so the canary
    tests the detector's discrimination of a known shift against no shift, independent of
    the run's actual v2 mean — a high-drift run must not collapse the canary.
    """
    base = replace(cfg, v2_sycophancy_mean=cfg.v1_sycophancy_mean)
    regressed_p = _arm_p_regression(base, seed, v2_shift=base.injected_shift)
    null_p = _arm_p_regression(base, seed + 1000, v2_shift=0.0)
    margin = regressed_p - null_p
    separated = margin >= cfg.min_canary_margin
    if separated:
        _log.info(
            "canary separated: margin=%.4f >= min_canary_margin=%.4f "
            "(regressed_p=%.4f null_p=%.4f)",
            margin,
            cfg.min_canary_margin,
            regressed_p,
            null_p,
        )
    else:
        _log.warning(
            "canary NOT separated: margin=%.4f < min_canary_margin=%.4f "
            "(regressed_p=%.4f null_p=%.4f); detector cannot be trusted",
            margin,
            cfg.min_canary_margin,
            regressed_p,
            null_p,
        )
    return CanaryReport(
        regressed_p=regressed_p,
        null_p=null_p,
        margin=margin,
        separated=separated,
    )
