"""Validation: reliability (primary metric), discrimination metrics, and the runner."""

from __future__ import annotations

from .metrics import aurc
from .reliability import ReliabilityReport, brier_reliability
from .runner import RunResult, run_suite

__all__ = [
    "ReliabilityReport",
    "RunResult",
    "aurc",
    "brier_reliability",
    "run_suite",
]
