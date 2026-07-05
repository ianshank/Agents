# pyright: reportMissingImports=false
"""ReAct-style specimen — interleaved reason/act steps with a confidence trace.

Introduced as the **type-holdout** flow: the harness calibrates on baseline+MCTS,
then ReAct is held out entirely to test generalization to an *unseen flow shape*.

Uncovered failure mode (vs baseline/MCTS): *late-step overconfidence*. ReAct keeps
acting until a step "looks done"; the final-step confidence is reported, which tends
to run higher than the trajectory deserves on hard instances — a confidence profile
distinct from the baseline's single shot and MCTS's vote fraction.

Deterministic given the injected RNG; ``max_steps`` is part of ``agent_config``.
"""

from __future__ import annotations

import random

from flow_protocol import ConfidenceChannel, FlowResult

from flow_corpus.policy.base import Policy
from flow_corpus.suites.base import TaskInstance

from .base import SpecimenBase, copy_flow_result


class ReActSpecimen(SpecimenBase):
    flow_type = "react"
    impl_version = "1"

    def __init__(
        self,
        policy: Policy,
        max_steps: int = 3,
        confidence_threshold: float = 0.5,
        agent_config: dict[str, object] | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        # Both knobs live in agent_config so changing either re-keys the agent.
        merged = {
            "max_steps": max_steps,
            "confidence_threshold": confidence_threshold,
            **(agent_config or {}),
        }
        super().__init__(policy, merged)
        self.max_steps = max_steps
        self.confidence_threshold = confidence_threshold

    def run(self, instance: TaskInstance, rng: random.Random) -> FlowResult:
        per_step: list[float] = []
        last = self.policy.decide(instance, rng)
        per_step.append(last.confidence if last.confidence is not None else 0.0)
        # Keep acting until confident enough or steps exhausted; report the LAST step.
        for _ in range(self.max_steps - 1):
            if last.confidence is not None and last.confidence >= self.confidence_threshold:
                break
            last = self.policy.decide(instance, rng)
            per_step.append(last.confidence if last.confidence is not None else 0.0)
        channel = ConfidenceChannel(per_step=tuple(per_step))
        result = self._result(instance, last.candidate, last.confidence, seed=None)
        return copy_flow_result(result, {"confidence_channel": channel})
