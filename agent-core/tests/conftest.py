"""Shared test configuration.

Registers Hypothesis profiles so example counts are config-driven, never hard-coded
per test: a fast ``dev`` default for local runs and a thorough ``ci`` profile selected
via ``HYPOTHESIS_PROFILE=ci`` (set in CI). The profile owns the knobs; test bodies stay
literal-free. The deepest invariant (isotonic monotonicity) keeps an explicit per-test
``@settings`` floor in test_property.py.
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
