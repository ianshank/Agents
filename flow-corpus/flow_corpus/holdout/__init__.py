"""Stratified holdout: instance-holdout (primary) vs type-holdout (generalization)."""

from __future__ import annotations

from .manager import HoldoutManager, HoldoutReport, Sample, samples_from_run
from .rotation import RotationManager, RotationReport

__all__ = [
    "HoldoutManager",
    "HoldoutReport",
    "RotationManager",
    "RotationReport",
    "Sample",
    "samples_from_run",
]
