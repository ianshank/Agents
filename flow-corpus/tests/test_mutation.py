"""Mutation engine: deterministic task perturbation that does NOT re-key the agent."""

from __future__ import annotations

import random

import pytest

from flow_corpus.config import CorpusConfig
from flow_corpus.mutation import MutationEngine
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import MCTSSpecimen
from flow_corpus.suites.sdlc import build_sdlc_suite

CFG = CorpusConfig(declared_n_per_domain=20)
SUITE = build_sdlc_suite(CFG, seed=3)


def test_mutation_is_deterministic() -> None:
    eng = MutationEngine()
    a = eng.mutate_suite(SUITE, n_variants=3, seed=5)
    b = eng.mutate_suite(SUITE, n_variants=3, seed=5)
    assert a.instances == b.instances
    assert len(a) == len(SUITE) * 3


def test_mutation_preserves_task_identity() -> None:
    eng = MutationEngine()
    mutated = eng.mutate_suite(SUITE, n_variants=2, seed=5)
    base = SUITE.instances[0]
    variants = [i for i in mutated.instances if i.instance_id.startswith(base.instance_id + "#")]
    assert len(variants) == 2
    for v in variants:
        assert v.solution_space == base.solution_space  # same task, perturbed conditions
        assert v.correct == base.correct


def test_mutation_does_not_rekey_agent() -> None:
    # Running the SAME specimen over mutated tasks must not change its agent_version.
    spec = MCTSSpecimen(MockPolicy(0.7), n_rollouts=5)
    eng = MutationEngine()
    mutated = eng.mutate_suite(SUITE, n_variants=2, seed=5)
    base_key = spec.run(SUITE.instances[0], random.Random(0)).agent_version
    mut_key = spec.run(mutated.instances[0], random.Random(0)).agent_version
    assert base_key == mut_key  # task perturbation excluded from the key


def test_mutation_validates_knobs() -> None:
    with pytest.raises(ValueError, match="difficulty_jitter"):
        MutationEngine(difficulty_jitter=1.5)


def test_mutate_suite_rejects_nonpositive_variants() -> None:
    with pytest.raises(ValueError, match="n_variants must be >= 1"):
        MutationEngine().mutate_suite(SUITE, n_variants=0)
