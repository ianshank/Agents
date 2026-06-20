"""Discrimination helpers that aggregate agent_core's curves.

``aurc`` integrates the area under the risk-coverage curve produced by
``agent_core.calibration.selective_risk_coverage`` (lower is better: a model that
commits to its confident-correct predictions first keeps risk low as coverage grows).
"""

from __future__ import annotations

from collections.abc import Sequence


def aurc(points: Sequence[tuple[float, float]]) -> float:
    """Area under the risk-coverage curve via the trapezoidal rule.

    Args:
        points: ``(coverage, risk)`` pairs as returned by ``selective_risk_coverage``
            (coverage non-decreasing).
    """
    if not points:
        raise ValueError("aurc requires at least one (coverage, risk) point")
    ordered = sorted(points, key=lambda p: p[0])
    area = 0.0
    prev_cov, prev_risk = ordered[0]
    # Seed the integral from coverage 0 using the first point's risk (flat segment).
    area += prev_cov * prev_risk
    for cov, risk in ordered[1:]:
        width = cov - prev_cov
        area += width * (prev_risk + risk) / 2.0
        prev_cov, prev_risk = cov, risk
    return area
