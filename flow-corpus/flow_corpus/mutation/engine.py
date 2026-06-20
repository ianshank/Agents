"""Perturb a task suite into a distribution of instances.

Each base instance spawns ``n_variants`` perturbed copies that jitter difficulty,
toggle tool availability, and add noise — turning a fixed suite into a population the
calibration metrics can be measured over with meaningful Wilson CIs (Phase 4).

Crucially this perturbs the *task*, never the agent: a mutated instance keeps the
same ``solution_space`` / ``correct`` identity (only its difficulty/tool/noise change)
and gets a derived ``instance_id``. Because the version key is impl + agent_config,
running an agent over mutated tasks does **not** re-key it — task variation is the
population axis, exactly as the keyer guarantees.

Deterministic given the seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from flow_corpus.suites.base import TaskInstance, TaskSuite


@dataclass(frozen=True)
class MutationEngine:
    difficulty_jitter: float = 0.15
    toggle_tool_prob: float = 0.25
    noise_jitter: float = 0.2

    def __post_init__(self) -> None:
        for name in ("difficulty_jitter", "toggle_tool_prob", "noise_jitter"):
            val = getattr(self, name)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

    def mutate_instance(
        self, instance: TaskInstance, rng: random.Random, suffix: str
    ) -> TaskInstance:
        difficulty = _clamp(
            instance.difficulty + rng.uniform(-self.difficulty_jitter, self.difficulty_jitter)
        )
        tool = (
            (not instance.tool_available)
            if rng.random() < self.toggle_tool_prob
            else instance.tool_available
        )
        noise = _clamp(instance.noise + rng.uniform(0.0, self.noise_jitter))
        return instance.model_copy(
            update={
                "instance_id": f"{instance.instance_id}#{suffix}",
                "difficulty": difficulty,
                "tool_available": tool,
                "noise": noise,
            }
        )

    def mutate_suite(self, suite: TaskSuite, *, n_variants: int = 3, seed: int = 0) -> TaskSuite:
        """Return a new suite with ``n_variants`` perturbed copies of each base instance."""
        if n_variants < 1:
            raise ValueError("n_variants must be >= 1")
        rng = random.Random(seed)
        mutated: list[TaskInstance] = []
        for instance in suite.instances:
            for k in range(n_variants):
                mutated.append(self.mutate_instance(instance, rng, f"m{k}"))
        return TaskSuite(domain=suite.domain, instances=tuple(mutated))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
