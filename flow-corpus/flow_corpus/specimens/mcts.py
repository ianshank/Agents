"""MCTS-style specimen — aggregate several policy rollouts by majority vote.

Uncovered failure mode (vs the baseline control): *confidence inflation under
correlated rollouts*. The vote-fraction confidence looks decisive even when all
rollouts share the policy's systematic error, so its calibration profile differs
from the baseline's — exactly the kind of variation the corpus must populate.

Deterministic given the injected RNG; ``n_rollouts`` is part of ``agent_config`` so
changing it re-keys the calibration unit.
"""

from __future__ import annotations

import random
from collections import Counter

from flow_protocol import ConfidenceChannel, FlowResult

from flow_corpus.policy.base import Policy
from flow_corpus.suites.base import TaskInstance

from .base import SpecimenBase


class MCTSSpecimen(SpecimenBase):
    flow_type = "mcts"
    impl_version = "1"

    def __init__(
        self,
        policy: Policy,
        n_rollouts: int = 5,
        agent_config: dict[str, object] | None = None,
    ) -> None:
        if n_rollouts < 1:
            raise ValueError("n_rollouts must be >= 1")
        merged = {"n_rollouts": n_rollouts, **(agent_config or {})}
        super().__init__(policy, merged)
        self.n_rollouts = n_rollouts

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        votes: Counter[str] = Counter()
        per_step: list[float] = []
        for _ in range(self.n_rollouts):
            decision = self.policy.decide(instance, rng)
            votes[decision.candidate] += 1
            if decision.confidence is not None:
                per_step.append(decision.confidence)
        candidate, top = votes.most_common(1)[0]
        vote_fraction = top / self.n_rollouts  # the aggregated (inflated) confidence
        channel = ConfidenceChannel(per_step=tuple(per_step)) if per_step else None
        result = self._result(instance, candidate, vote_fraction, seed=None)
        return result.model_copy(update={"confidence_channel": channel})
