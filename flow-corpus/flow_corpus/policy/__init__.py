"""The policy seam: how a specimen decides on a candidate for an instance.

Specimens are policy-injected so they run deterministically offline (``MockPolicy``)
yet can swap a real LLM-backed policy without changing the flow logic — mirroring the
harness's ``Judge`` / ``MockJudge`` pattern.
"""

from __future__ import annotations

from .base import Policy, PolicyDecision
from .mock import MockPolicy

__all__ = ["MockPolicy", "Policy", "PolicyDecision"]
