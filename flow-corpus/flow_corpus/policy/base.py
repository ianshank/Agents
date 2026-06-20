"""Policy protocol: one decision (candidate + optional confidence) per query.

A flow may query its policy once (baseline) or many times (MCTS rollouts). The
policy receives an injected ``random.Random`` so all stochasticity is seeded and
reproducible; the seed is recorded on the FlowResult, never folded into the key.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from flow_corpus.suites.base import TaskInstance


@dataclass(frozen=True)
class PolicyDecision:
    """One sampled decision. ``confidence`` is None for confidence-free policies."""

    candidate: str
    confidence: float | None = None


@runtime_checkable
class Policy(Protocol):
    def decide(self, instance: TaskInstance, rng: random.Random) -> PolicyDecision:
        """Return a single decision for *instance*, drawing randomness from *rng*."""
        ...
