"""Holdout rotation + primary-metric stability.

Anti-overfit discipline (Phase 4): rotate which instances form the measured
(held-out) partition across ``k`` folds and check that the primary metric — Brier
reliability — is *stable* across rotations. A metric that swings wildly as the fold
changes is overfit to a particular partition, not a property of the agent.

Each fold reuses the single split authority (``HoldoutManager``) with a different
seed, so the partition rotates deterministically. Stability gate: the spread
(max - min) of per-fold reliability must be within ``rotation_stability_threshold``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from flow_corpus.config import CorpusConfig

from .manager import HoldoutManager, Sample


@dataclass(frozen=True)
class RotationReport:
    per_fold_reliability: tuple[float, ...]
    spread: float  # max - min across measurable folds
    stable: bool  # >= 2 measurable folds AND spread <= cfg.rotation_stability_threshold
    n_folds: int
    directional_folds: int  # folds whose instance-holdout was below power / unmeasurable

    @property
    def passes(self) -> bool:
        return self.stable


def _spread_and_stable(reliabilities: list[float], threshold: float) -> tuple[float, bool]:
    """Spread and stability verdict over per-fold reliabilities.

    Stability is *undefined* with fewer than two measurable folds — a single value has a
    trivially-zero spread, which must NOT be reported as stable. So <2 folds → not stable.
    """
    if len(reliabilities) < 2:
        return (0.0, False)
    spread = max(reliabilities) - min(reliabilities)
    return (spread, spread <= threshold)


class RotationManager:
    def __init__(self, cfg: CorpusConfig) -> None:
        self.cfg = cfg

    def rotate(
        self,
        samples_by_type: Mapping[str, Sequence[Sample]],
        held_out_type: str,
        *,
        k_folds: int = 3,
        base_seed: int = 0,
    ) -> RotationReport:
        """Measure instance-holdout reliability across ``k_folds`` rotated partitions."""
        if k_folds < 2:
            raise ValueError("k_folds must be >= 2 to assess stability")

        reliabilities: list[float] = []
        directional = 0
        for fold in range(k_folds):
            manager = HoldoutManager(self.cfg, seed=base_seed + fold)
            report = manager.evaluate(samples_by_type, held_out_type)
            rel = report.instance_holdout.reliability
            if rel is None:
                # No measurable instances this fold — treat as a degenerate fold.
                directional += 1
                continue
            if report.instance_holdout.directional_only:
                directional += 1
            reliabilities.append(rel)

        if not reliabilities:
            raise ValueError("no fold produced a measurable instance-holdout reliability")

        spread, stable = _spread_and_stable(reliabilities, self.cfg.rotation_stability_threshold)
        return RotationReport(
            per_fold_reliability=tuple(reliabilities),
            spread=spread,
            stable=stable,
            n_folds=k_folds,
            directional_folds=directional,
        )
