"""Discrimination canary: proves the corpus can tell a good agent from a bad one."""

from __future__ import annotations

from .separation import SeparationReport, canary_separation
from .specimens import GoldSpecimen, NoOpSpecimen, RandomSpecimen

__all__ = [
    "GoldSpecimen",
    "NoOpSpecimen",
    "RandomSpecimen",
    "SeparationReport",
    "canary_separation",
]
