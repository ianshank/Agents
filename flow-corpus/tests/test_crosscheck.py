"""Confidence cross-check: ablation vs flow-type indicator + bootstrap significance."""

from __future__ import annotations

import random

from flow_corpus.config import CorpusConfig
from flow_corpus.crosscheck import CrossCheckRow, confidence_cross_check
from flow_corpus.validation.resampling import bootstrap_delta_ci

CFG = CorpusConfig(power_min_sample=40)


def _rows_confidence_informative(n: int = 400) -> list[CrossCheckRow]:
    # Confidence genuinely predicts the outcome (beyond flow identity).
    rng = random.Random(0)
    rows: list[CrossCheckRow] = []
    for i in range(n):
        ftype = "baseline" if i % 2 == 0 else "mcts"
        p = rng.random()
        outcome = 1 if rng.random() < p else 0
        rows.append(
            CrossCheckRow(flow_type=ftype, instance_id=f"i{i}", confidence=p, outcome=outcome)
        )
    return rows


def _rows_confidence_is_flow_identity(n: int = 400) -> list[CrossCheckRow]:
    # Confidence is constant per flow type and equals its base rate -> no added signal.
    rng = random.Random(1)
    rows: list[CrossCheckRow] = []
    for i in range(n):
        if i % 2 == 0:
            ftype, rate = "baseline", 0.3
        else:
            ftype, rate = "mcts", 0.7
        outcome = 1 if rng.random() < rate else 0
        rows.append(
            CrossCheckRow(flow_type=ftype, instance_id=f"i{i}", confidence=rate, outcome=outcome)
        )
    return rows


def test_informative_confidence_adds_signal() -> None:
    report = confidence_cross_check(_rows_confidence_informative(), CFG, seed=2, n_resamples=500)
    assert report.auroc_confidence is not None
    assert report.delta_ci is not None
    assert report.confidence_adds_signal is True  # signed + significant
    assert report.delta_ci.point > 0


def test_flow_identity_confidence_adds_no_signal() -> None:
    report = confidence_cross_check(
        _rows_confidence_is_flow_identity(), CFG, seed=2, n_resamples=500
    )
    # Confidence == flow base rate -> indicator matches confidence -> delta ~ 0, not significant.
    assert report.confidence_adds_signal is False


def test_directional_below_power() -> None:
    rows = _rows_confidence_informative(20)  # measure partition will be < power_min_sample
    report = confidence_cross_check(rows, CFG, seed=2, n_resamples=200)
    assert report.directional_only is True
    assert report.confidence_adds_signal is False


def test_bootstrap_ci_excludes_zero_property() -> None:
    ci = bootstrap_delta_ci(
        [1.0, 1.0, 1.0], [0.0, 0.0, 0.0], [1, 1, 0], lambda s, o: sum(s), n_resamples=100, seed=0
    )
    assert ci.point == 3.0
    assert ci.excludes_zero is True
