"""Canary specimens: deterministic upper/lower bounds on agent quality.

* ``GoldSpecimen`` — an oracle-peeking agent that always picks a correct candidate
  with full confidence (the high-trust bound).
* ``NoOpSpecimen`` — always picks a wrong candidate (the low-trust bound). It reports
  no confidence: an outcome-only flow, which is exactly why the canary separation is
  measured on pass-rate rather than AUROC (a single-class slice has no AUROC).
* ``RandomSpecimen`` — picks uniformly at random (seeded), a weak-but-not-zero agent.

These bypass the policy seam by construction (they are reference agents, not models).
"""

from __future__ import annotations

import random

from flow_corpus.policy.base import PolicyDecision
from flow_corpus.suites.base import TaskInstance

from ..specimens.base import FlowResult, SpecimenBase


class _CanaryBase(SpecimenBase):
    def __init__(self) -> None:
        # Canary agents carry no tunable config; their identity is the impl alone.
        super().__init__(policy=_NULL_POLICY, agent_config={})


class GoldSpecimen(_CanaryBase):
    flow_type = "gold"
    impl_version = "1"

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        return self._result(instance, instance.correct[0], confidence=1.0, seed=None)


class NoOpSpecimen(_CanaryBase):
    flow_type = "noop"
    impl_version = "1"

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        # Always wrong, and no self-reported confidence (outcome-only flow).
        return self._result(instance, instance.wrong[0], confidence=None, seed=None)


class RandomSpecimen(_CanaryBase):
    flow_type = "random"
    impl_version = "1"

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        candidate = instance.solution_space[rng.randrange(len(instance.solution_space))]
        return self._result(instance, candidate, confidence=rng.random(), seed=None)


class _NullPolicy:
    """Placeholder policy; canary agents never query it."""

    def decide(
        self, instance: TaskInstance, rng: random.Random
    ) -> PolicyDecision:  # pragma: no cover
        raise RuntimeError("canary specimens do not use a policy")


_NULL_POLICY = _NullPolicy()
