"""End-to-end orchestration: the 7-beat run wired together, offline and deterministic.

``run_pipeline`` is byte-reproducible from ``(BRConfig, seed)``. A ``judge`` may be
injected (e.g. a live adapter satisfying ``JudgeProtocol`` supplied by the harness layer);
when omitted, the deterministic :class:`SyntheticJudge` is used and the run requires no
network. In this synthetic world the per-pair ground truth doubles as the human-audit
label set the oracle validates the judge against.
"""

from __future__ import annotations

import random

from agent_core.calibration import Bin, reliability_bins

from .canary import run_canary
from .config import BRConfig
from .detector import RegressionDetector, labelled_correctness
from .gate import decide_ship
from .generator import (
    PairedResponseGenerator,
    ground_truth_regressions,
    sycophancy_indicators,
)
from .judge import JudgeProtocol, SyntheticJudge
from .oracle import validate_judge
from .report import RegressionReport


def run_pipeline(
    cfg: BRConfig, *, seed: int, judge: JudgeProtocol | None = None
) -> RegressionReport:
    """Run generate → judge → validate → detect → canary → gate → report."""
    gen_rng = random.Random(seed)
    pairs = PairedResponseGenerator(cfg).generate(gen_rng)

    if judge is None:
        judge = SyntheticJudge(cfg, random.Random(seed + 1))
    verdicts = [judge.judge(p) for p in pairs]

    # Synthetic human-audit labels: the latent ground truth for each pair.
    human_labels: list[bool | None] = list(ground_truth_regressions(pairs))

    kappa = validate_judge(verdicts, human_labels, cfg)

    v1_ind, v2_ind = sycophancy_indicators(pairs)
    estimate = RegressionDetector(cfg).detect(v1_ind, v2_ind, verdicts, human_labels, seed=seed + 2)

    canary = run_canary(cfg, seed + 3)
    decision = decide_ship(estimate, kappa, canary, cfg)

    confidences, correct = labelled_correctness(verdicts, human_labels)
    bins: list[Bin] = reliability_bins(confidences, correct, cfg.n_bins) if confidences else []

    return RegressionReport(
        estimate=estimate,
        kappa=kappa,
        canary=canary,
        decision=decision,
        bins=bins,
    )
