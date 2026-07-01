"""Small shared formatting helpers for HTML/text reports.

Kept deliberately tiny: these are pure, deterministic string formatters shared
by the comparison (F-024) and A/B campaign (F-025) report renderers so the same
number formatting is used everywhere.
"""

from __future__ import annotations


def _fmt(value: float | None) -> str:
    """Format an optional float to 3 decimals, or ``"n/a"`` when ``None``."""
    return "n/a" if value is None else f"{value:.3f}"
