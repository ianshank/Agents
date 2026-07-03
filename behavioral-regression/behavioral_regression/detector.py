"""Calibrated regression detector.

Reports the v1→v2 regression as a *probability with an interval*, never a point claim,
and emits an explicit ``cant_tell`` bucket where the measurement stops working. It reuses
proven primitives rather than re-deriving statistics:

* ``agent_core.calibration.wilson_interval`` — CI on the regression proportion.
* ``agent_core.calibration.brier_score`` / ``brier_decomposition`` — judge calibration.
* ``flow_corpus.validation.resampling.bootstrap_delta_ci`` — seeded percentile CI on the
  v2-v1 sycophancy-rate delta; ``excludes_zero`` is the significance signal.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.calibration import brier_decomposition, brier_score, wilson_interval
from agent_core.logging_util import get_logger
from flow_corpus.validation.power import is_directional_only
from flow_corpus.validation.resampling import BootstrapCI, bootstrap_delta_ci

from .config import BRConfig
from .judge import JVerdict

_log = get_logger("behavioral_regression.detector")


def _mean(scores: Sequence[float], _outcomes: Sequence[int]) -> float:
    """Mean of ``scores`` (the bootstrap statistic; outcomes are unused for a rate)."""
    return sum(scores) / len(scores)


def labelled_correctness(
    verdicts: Sequence[JVerdict], human_labels: Sequence[bool | None]
) -> tuple[list[float], list[int]]:
    """Return ``(confidences, correctness)`` over the labelled, determinate subset.

    A pair contributes only when both the judge verdict and the human label are
    determinate; correctness is 1 when the judge agrees with the human label. Shared by
    the detector's Brier metrics and the report's reliability diagram so both bin the
    same data.
    """
    if len(verdicts) != len(human_labels):
        raise ValueError("verdicts and human_labels must be aligned (equal length)")
    confidences: list[float] = []
    correct: list[int] = []
    for v, h in zip(verdicts, human_labels, strict=True):
        if v.label is not None and h is not None:
            confidences.append(v.confidence)
            correct.append(1 if v.label == h else 0)
    return confidences, correct


@dataclass(frozen=True)
class RegressionEstimate:
    p_regression: float  # calibrated probability v2 drifted more sycophantic than v1
    wilson_low: float
    wilson_high: float
    delta_ci: BootstrapCI  # bootstrap CI on sycophancy-rate(v2) - rate(v1)
    brier: float | None  # judge confidence calibration; None when no labelled data
    reliability: float | None  # Brier reliability term; None when no labelled data
    n_determinate: int
    cant_tell: bool  # the honest abstain bucket

    @property
    def excludes_zero(self) -> bool:
        return bool(self.delta_ci.excludes_zero)


class RegressionDetector:
    def __init__(self, cfg: BRConfig) -> None:
        self._cfg = cfg

    def detect(
        self,
        v1_indicators: Sequence[int],
        v2_indicators: Sequence[int],
        verdicts: Sequence[JVerdict],
        human_labels: Sequence[bool | None] | None,
        *,
        seed: int,
    ) -> RegressionEstimate:
        cfg = self._cfg
        n = len(v1_indicators)
        if not (len(v2_indicators) == len(verdicts) == n):
            raise ValueError("indicators and verdicts must be aligned (equal length)")
        if n == 0:
            raise ValueError("cannot detect on an empty sample")

        # Bootstrap CI on the v2-v1 sycophancy-rate delta (paired rows preserved).
        dummy_outcomes = [0] * n
        delta_ci = bootstrap_delta_ci(
            [float(x) for x in v2_indicators],
            [float(x) for x in v1_indicators],
            dummy_outcomes,
            _mean,
            n_resamples=cfg.bootstrap_resamples,
            alpha=cfg.bootstrap_alpha,
            seed=seed,
        )

        # Regression proportion from the judge's determinate verdicts + Wilson CI.
        determinate = [v for v in verdicts if v.label is not None]
        n_det = len(determinate)
        if n_det == 0:
            _log.warning("no determinate verdicts out of %d pairs; p_regression degrades to 0.0", n)
        k = sum(1 for v in determinate if v.label)
        p_regression = k / n_det if n_det > 0 else 0.0
        wilson_low, wilson_high = wilson_interval(k, n_det, cfg.wilson_z)

        # Judge calibration on the labelled, determinate subset (confidence vs correctness).
        brier: float | None = None
        reliability: float | None = None
        if human_labels is not None:
            if len(human_labels) != n:
                raise ValueError("human_labels must be aligned with verdicts")
            confidences, correct = labelled_correctness(verdicts, human_labels)
            if confidences:
                brier = brier_score(confidences, correct)
                reliability = brier_decomposition(confidences, correct, cfg.n_bins).reliability

        directional = is_directional_only(n_det, cfg.power_min_sample)
        cant_tell = (not delta_ci.excludes_zero) or directional
        _log.debug(
            "delta_ci point=%.4f low=%.4f high=%.4f excludes_zero=%s directional_only=%s",
            delta_ci.point,
            delta_ci.low,
            delta_ci.high,
            delta_ci.excludes_zero,
            directional,
        )
        _log.info(
            "detect: p_regression=%.4f wilson=[%.4f, %.4f] n_determinate=%d/%d cant_tell=%s",
            p_regression,
            wilson_low,
            wilson_high,
            n_det,
            n,
            cant_tell,
        )
        return RegressionEstimate(
            p_regression=p_regression,
            wilson_low=wilson_low,
            wilson_high=wilson_high,
            delta_ci=delta_ci,
            brier=brier,
            reliability=reliability,
            n_determinate=n_det,
            cant_tell=cant_tell,
        )
