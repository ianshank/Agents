"""Shared pytest configuration: Hypothesis profiles + markers (mirrors sibling packages)."""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=50)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
