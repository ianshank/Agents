"""Confidence cross-check with a flow-type-indicator ablation + significance test.

The worry (defect S6 in the spec's review): a flow's confidence might look predictive
only because it encodes *which flow* produced it (e.g. MCTS always reports ~0.9).
To rule that out we compare, on a HELD-OUT partition:

* ``auroc_confidence`` — AUROC of the raw confidence predicting correctness, vs
* ``auroc_flow_indicator`` — AUROC of a pure flow-type indicator (each row scored by
  its flow type's base rate, learned on the *fit* partition only).

Significance is a seeded bootstrap CI on the AUROC delta (DeLong deferred per the
plan). Confidence "adds signal" only when the delta is positive AND its CI excludes 0.
Below ``power_min_sample`` held-out rows the result is directional only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.calibration import auroc
from agent_core.logging_util import get_logger

from flow_corpus.config import CorpusConfig
from flow_corpus.partition import bucket
from flow_corpus.validation.power import is_directional_only
from flow_corpus.validation.resampling import BootstrapCI, bootstrap_delta_ci

# Neutral base rate for a flow type unseen in the fit partition (binary outcome).
_NEUTRAL_RATE = 0.5

_log = get_logger("flow_corpus.crosscheck.confidence")


@dataclass(frozen=True)
class CrossCheckRow:
    flow_type: str
    instance_id: str
    confidence: float
    outcome: int


@dataclass(frozen=True)
class CrossCheckReport:
    auroc_confidence: float | None
    auroc_flow_indicator: float | None
    delta_ci: BootstrapCI | None
    confidence_adds_signal: bool
    n_measured: int
    directional_only: bool


def _row_bucket(seed: int, row: CrossCheckRow) -> float:
    return bucket(seed, f"{row.flow_type}:{row.instance_id}")


def confidence_cross_check(
    rows: Sequence[CrossCheckRow],
    cfg: CorpusConfig,
    *,
    seed: int = 0,
    n_resamples: int | None = None,
) -> CrossCheckReport:
    """Run the held-out, ablated, significance-tested confidence cross-check.

    ``n_resamples`` defaults to ``cfg.bootstrap_resamples`` when not overridden.
    """
    resamples = cfg.bootstrap_resamples if n_resamples is None else n_resamples
    edge = cfg.holdout_fit_fraction
    fit = [r for r in rows if _row_bucket(seed, r) < edge]
    measure = [r for r in rows if _row_bucket(seed, r) >= edge]

    # Flow-type indicator learned on the FIT partition only (no leakage into measure).
    global_rate = (sum(r.outcome for r in fit) / len(fit)) if fit else _NEUTRAL_RATE
    by_type: dict[str, list[int]] = {}
    for r in fit:
        by_type.setdefault(r.flow_type, []).append(r.outcome)
    base_rate = {t: sum(v) / len(v) for t, v in by_type.items()}

    _log.debug(
        "cross-check split n_fit=%d n_measured=%d n_fit_flow_types=%d",
        len(fit),
        len(measure),
        len(base_rate),
    )
    directional = is_directional_only(len(measure), cfg.power_min_sample)
    outcomes = [r.outcome for r in measure]
    if len(measure) == 0 or len(set(outcomes)) < 2:
        # AUROC undefined without both classes present in the held-out slice.
        _log.warning(
            "confidence cross-check degenerate measure partition (AUROC undefined); "
            "returning directional-only n_measured=%d",
            len(measure),
        )
        return CrossCheckReport(None, None, None, False, len(measure), directional_only=True)

    conf_scores = [r.confidence for r in measure]
    indicator_scores = [base_rate.get(r.flow_type, global_rate) for r in measure]

    auroc_conf = auroc(conf_scores, outcomes)
    auroc_ind = auroc(indicator_scores, outcomes)
    ci = bootstrap_delta_ci(
        conf_scores,
        indicator_scores,
        outcomes,
        auroc,
        n_resamples=resamples,
        alpha=cfg.bootstrap_alpha,
        seed=seed,
    )
    adds_signal = (not directional) and ci.point > 0.0 and ci.excludes_zero
    _log.info(
        "confidence cross-check auroc_confidence=%.4f auroc_flow_indicator=%.4f "
        "delta=%.4f excludes_zero=%s n_measured=%d adds_signal=%s",
        auroc_conf,
        auroc_ind,
        ci.point,
        ci.excludes_zero,
        len(measure),
        adds_signal,
    )
    return CrossCheckReport(
        auroc_confidence=auroc_conf,
        auroc_flow_indicator=auroc_ind,
        delta_ci=ci,
        confidence_adds_signal=adds_signal,
        n_measured=len(measure),
        directional_only=directional,
    )
