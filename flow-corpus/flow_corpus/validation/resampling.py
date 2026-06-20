"""Seeded percentile bootstrap for confidence intervals on metric deltas.

Pure and dependency-free (stdlib ``random`` only) so it could migrate into
``agent_core`` later. Used by the confidence cross-check to put a CI on the
difference between two paired statistics and decide significance (CI excludes 0).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

Statistic = Callable[[Sequence[int], Sequence[int]], float]


@dataclass(frozen=True)
class BootstrapCI:
    point: float
    low: float
    high: float
    n_resamples: int

    @property
    def excludes_zero(self) -> bool:
        """Significant at the CI's level if the whole interval is above or below 0."""
        return self.low > 0.0 or self.high < 0.0


def bootstrap_delta_ci(
    a_scores: Sequence[float],
    b_scores: Sequence[float],
    outcomes: Sequence[int],
    statistic: Callable[[Sequence[float], Sequence[int]], float],
    *,
    n_resamples: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> BootstrapCI:
    """Percentile-bootstrap CI for ``statistic(a) - statistic(b)`` over paired rows.

    The three sequences are aligned per row (a_scores[i], b_scores[i], outcomes[i]);
    each resample draws row indices with replacement so the pairing is preserved.
    """
    n = len(outcomes)
    if not (len(a_scores) == len(b_scores) == n):
        raise ValueError("a_scores, b_scores, outcomes must be aligned (equal length)")
    if n == 0:
        raise ValueError("cannot bootstrap an empty sample")

    point = statistic(a_scores, outcomes) - statistic(b_scores, outcomes)
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        ra = [a_scores[i] for i in idx]
        rb = [b_scores[i] for i in idx]
        ro = [outcomes[i] for i in idx]
        try:
            deltas.append(statistic(ra, ro) - statistic(rb, ro))
        except ValueError:
            # Degenerate resample (e.g. single-class slice for AUROC) — skip it.
            continue
    if not deltas:
        raise ValueError("all bootstrap resamples were degenerate")
    deltas.sort()
    lo_idx = max(0, int((alpha / 2) * len(deltas)) - 1)
    hi_idx = min(len(deltas) - 1, int((1 - alpha / 2) * len(deltas)))
    return BootstrapCI(
        point=point, low=deltas[lo_idx], high=deltas[hi_idx], n_resamples=len(deltas)
    )
