"""Specimen tests: determinism, keying behaviour, and the registry."""

from __future__ import annotations

import random

import pytest

from flow_corpus.policy import MockPolicy  # type: ignore
from flow_corpus.specimens import (  # type: ignore
    SPECIMENS,
    BaselineSpecimen,
    MCTSSpecimen,
    ReActSpecimen,
)
from flow_corpus.suites.base import TaskInstance  # type: ignore

INSTANCE = TaskInstance(
    instance_id="t1",
    domain="sdlc",
    difficulty=0.2,
    solution_space=("a", "b", "c", "d"),
    correct=("a",),
)


def test_baseline_is_deterministic_under_same_seed() -> None:
    spec = BaselineSpecimen(MockPolicy(skill=0.7))
    r1 = spec.run(INSTANCE, random.Random(0))
    r2 = spec.run(INSTANCE, random.Random(0))
    assert r1 == r2
    assert r1.flow_type == "baseline"
    assert r1.output in INSTANCE.solution_space


def test_mcts_aggregates_and_emits_confidence_channel() -> None:
    spec = MCTSSpecimen(MockPolicy(skill=0.9), n_rollouts=5)
    r = spec.run(INSTANCE, random.Random(1))
    assert r.flow_type == "mcts"
    assert r.raw_confidence is not None and 0.0 <= r.raw_confidence <= 1.0
    assert r.confidence_channel is not None
    assert len(r.confidence_channel.per_step) == 5


def test_task_does_not_rekey_but_config_does() -> None:
    spec = MCTSSpecimen(MockPolicy(skill=0.9), n_rollouts=5)
    other_instance = INSTANCE.model_copy(update={"instance_id": "t2", "difficulty": 0.9})
    r_a = spec.run(INSTANCE, random.Random(2))
    r_b = spec.run(other_instance, random.Random(2))
    # Same specimen, different task -> SAME agent_version (task excluded from the key).
    assert r_a.agent_version == r_b.agent_version
    # Different rollout count -> DIFFERENT agent_version (config is in the key).
    spec2 = MCTSSpecimen(MockPolicy(skill=0.9), n_rollouts=7)
    assert spec2.agent_version != spec.agent_version


def test_react_is_deterministic_and_emits_channel() -> None:
    spec = ReActSpecimen(MockPolicy(skill=0.6), max_steps=3)
    r1 = spec.run(INSTANCE, random.Random(0))
    r2 = spec.run(INSTANCE, random.Random(0))
    assert r1 == r2
    assert r1.flow_type == "react"
    assert r1.confidence_channel is not None and len(r1.confidence_channel.per_step) >= 1


def test_react_rejects_nonpositive_steps() -> None:
    with pytest.raises(ValueError, match="max_steps must be >= 1"):
        ReActSpecimen(MockPolicy(), max_steps=0)


def test_react_confidence_threshold_rekeys_and_validates() -> None:
    a = ReActSpecimen(MockPolicy(0.7), max_steps=3, confidence_threshold=0.5)
    b = ReActSpecimen(MockPolicy(0.7), max_steps=3, confidence_threshold=0.8)
    assert a.agent_version != b.agent_version  # threshold is in the key
    with pytest.raises(ValueError, match="confidence_threshold"):
        ReActSpecimen(MockPolicy(), confidence_threshold=1.5)


class _ConfidenceFreePolicy:
    """Policy that returns no confidence, exercising the confidence-None branches."""

    def decide(self, instance, rng: random.Random):
        from flow_corpus.policy.base import PolicyDecision  # type: ignore

        return PolicyDecision(candidate=instance.solution_space[0], confidence=None)


def test_mcts_handles_confidence_free_policy() -> None:
    spec = MCTSSpecimen(_ConfidenceFreePolicy(), n_rollouts=4)
    r = spec.run(INSTANCE, random.Random(0))
    # No per-step confidences collected -> no ConfidenceChannel; vote fraction still set.
    assert r.confidence_channel is None
    assert r.raw_confidence is not None


def test_registry_lookup() -> None:
    assert SPECIMENS.get("baseline") is BaselineSpecimen
    assert SPECIMENS.get("mcts") is MCTSSpecimen
    assert SPECIMENS.get("react") is ReActSpecimen
    assert set(SPECIMENS.names()) == {"baseline", "mcts", "react"}


def test_registry_rejects_duplicate_and_unknown() -> None:

    with pytest.raises(ValueError, match="already registered"):
        SPECIMENS.register("baseline", BaselineSpecimen)
    with pytest.raises(KeyError, match="unknown specimen"):
        SPECIMENS.get("nope")


def test_mcts_rejects_nonpositive_rollouts() -> None:

    with pytest.raises(ValueError, match="n_rollouts must be >= 1"):
        MCTSSpecimen(MockPolicy(), n_rollouts=0)


def test_mock_policy_validates_ranges() -> None:

    with pytest.raises(ValueError, match="skill"):
        MockPolicy(skill=1.5)
    with pytest.raises(ValueError, match="confidence_quality"):
        MockPolicy(confidence_quality=-0.1)


def test_mock_policy_tool_unavailable_lowers_success() -> None:
    # Cover the no-tool offset branch deterministically.
    from flow_corpus.suites.base import TaskInstance

    no_tool = TaskInstance(
        instance_id="nt",
        domain="sdlc",
        difficulty=0.0,
        solution_space=("a", "b", "c", "d"),
        correct=("a",),
        tool_available=False,
    )
    policy = MockPolicy(skill=0.5, confidence_quality=1.0)
    # p_correct = 0.5 - 0.1 = 0.4; confidence equals p_correct at quality 1.0.
    dec = policy.decide(no_tool, random.Random(0))
    assert dec.confidence == pytest.approx(0.4)
