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
    spread: float  # max - min across folds
    stable: bool  # spread <= cfg.rotation_stability_threshold
    n_folds: int
    directional_folds: int  # folds whose instance-holdout was below power

    @property
    def passes(self) -> bool:
        return self.stable


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

        spread = max(reliabilities) - min(reliabilities)
        return RotationReport(
            per_fold_reliability=tuple(reliabilities),
            spread=spread,
            stable=spread <= self.cfg.rotation_stability_threshold,
            n_folds=k_folds,
            directional_folds=directional,
        )
