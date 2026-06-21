"""A deterministic, seeded mock policy that models a parametrised agent.

``MockPolicy`` simulates an agent of a given ``skill`` whose self-reported
``confidence`` tracks its true success probability to the degree set by
``confidence_quality``. This is what gives the corpus a real calibration signal to
measure: a high ``confidence_quality`` agent is well-calibrated (low Brier
reliability); a low one reports noise (poor reliability/resolution).

It is a *mock* of a flow's underlying model, not a flow itself — specimens compose
one or more MockPolicy queries into a flow shape.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from flow_corpus.suites.base import TaskInstance

from .base import PolicyDecision


@dataclass(frozen=True)
class MockPolicy:
    skill: float = 0.7
    """Base probability of selecting a correct candidate on a difficulty-0 instance."""

    confidence_quality: float = 1.0
    """How tightly reported confidence tracks the true success probability (0..1)."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.skill <= 1.0:
            raise ValueError("skill must be in [0, 1]")
        if not 0.0 <= self.confidence_quality <= 1.0:
            raise ValueError("confidence_quality must be in [0, 1]")

    def _p_correct(self, instance: TaskInstance) -> float:
        # Difficulty erodes success; a tool, when available, partly offsets it.
        offset = 0.0 if instance.tool_available else 0.1
        return max(0.0, min(1.0, self.skill * (1.0 - instance.difficulty) - offset))

    def decide(self, instance: TaskInstance, rng: random.Random) -> PolicyDecision:
        p_correct = self._p_correct(instance)
        is_correct = rng.random() < p_correct
        if is_correct:
            candidate = instance.correct[rng.randrange(len(instance.correct))]
        else:
            wrong = instance.wrong
            candidate = wrong[rng.randrange(len(wrong))]
        # Reported confidence: blend the true success probability with noise.
        confidence = (
            self.confidence_quality * p_correct + (1.0 - self.confidence_quality) * rng.random()
        )
        return PolicyDecision(candidate=candidate, confidence=max(0.0, min(1.0, confidence)))
