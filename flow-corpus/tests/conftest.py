"""Shared test configuration.

Registers Hypothesis profiles so example counts are config-driven (a fast ``dev``
default, a thorough ``ci`` profile selected via ``HYPOTHESIS_PROFILE=ci``), mirroring
agent-core's conftest. Property tests use the ``property`` marker.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=50)
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,  # CI runners are noisy; no per-example wall-clock deadline
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
