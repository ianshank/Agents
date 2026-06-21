"""Statistical-power helper: below a derived minimum, a metric is directional only.

The rule (spec METHODS NOTE): any metric reported on fewer than a power-derived
minimum sample is *directional only* and cannot gate a phase. Centralised here so the
reliability report, the holdout manager, and the κ-gate all apply one definition.
"""

from __future__ import annotations


def is_directional_only(n: int, power_min_sample: int) -> bool:
    """True when a sample of size *n* is too small to gate (n < power_min_sample)."""
    return n < power_min_sample
