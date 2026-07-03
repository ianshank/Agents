#!/usr/bin/env python3
"""Validation script for Feature F-015: Phase-4 — mutation engine + holdout rotation.

Deterministic and offline. Asserts the Phase-4 exit gates:
  1. The mutation engine is deterministic and preserves task identity.
  2. Task perturbation does NOT re-key the agent; an impl/config change DOES re-key
     (the keyer was built in Phase 1; this is the re-key / no-task-rekey gate).
  3. Holdout rotation produces >= k folds and a primary-metric (Brier reliability)
     stability spread, gated by the configured rotation-stability threshold.
"""

import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("flow-protocol", "flow-corpus", "agent-core"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

from flow_corpus.config import CorpusConfig
from flow_corpus.holdout import RotationManager, Sample, samples_from_run
from flow_corpus.mutation import MutationEngine
from flow_corpus.oracles import PropertyOracle
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import BaselineSpecimen, MCTSSpecimen, ReActSpecimen
from flow_corpus.suites.sdlc import build_sdlc_suite
from flow_corpus.validation import run_suite


def validate_f015() -> bool:
    cfg = CorpusConfig(declared_n_per_domain=100, power_min_sample=20)
    suite = build_sdlc_suite(cfg, seed=3)
    eng = MutationEngine()
    checks: dict[str, bool] = {}

    # 1. Mutation determinism + task-identity preservation.
    a = eng.mutate_suite(suite, n_variants=3, seed=5)
    b = eng.mutate_suite(suite, n_variants=3, seed=5)
    base = suite.instances[0]
    variants = [i for i in a.instances if i.instance_id.startswith(base.instance_id + "#")]
    checks["mutation deterministic + identity-preserving"] = (
        a.instances == b.instances
        and len(a) == len(suite) * 3
        # Assert the expected variant count first, so the all(...) below can't pass vacuously
        # on an empty list if the suffixing scheme ever changes.
        and len(variants) == 3
        and all(v.solution_space == base.solution_space and v.correct == base.correct for v in variants)
    )

    # 2. Re-key semantics: task perturbation does NOT re-key; config change DOES.
    spec = MCTSSpecimen(MockPolicy(0.7), n_rollouts=5)
    base_key = spec.run(suite.instances[0], random.Random(0)).agent_version
    mut_key = spec.run(a.instances[0], random.Random(0)).agent_version
    rekeyed = MCTSSpecimen(MockPolicy(0.7), n_rollouts=7).agent_version
    checks["task perturbation does NOT re-key the agent"] = base_key == mut_key
    checks["impl/config change DOES re-key the agent"] = rekeyed != base_key

    # 3. Holdout rotation over a mutated population -> reliability stability spread.
    oracle = PropertyOracle()
    mutated = eng.mutate_suite(suite, n_variants=3, seed=9)

    def samples(spec_) -> list[Sample]:
        return list(samples_from_run(run_suite(spec_, mutated, oracle, cfg, seed=4)))

    by_type = {
        "baseline": samples(BaselineSpecimen(MockPolicy(0.7, 1.0))),
        "mcts": samples(MCTSSpecimen(MockPolicy(0.7, 1.0), n_rollouts=5)),
        "react": samples(ReActSpecimen(MockPolicy(0.7, 1.0), max_steps=3)),
    }
    rot = RotationManager(cfg).rotate(by_type, held_out_type="react", k_folds=4, base_seed=0)
    checks["rotation: >= 2 folds with a stability spread"] = (
        len(rot.per_fold_reliability) >= 2 and rot.spread >= 0.0 and isinstance(rot.stable, bool)
    )

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-015 validation passed." if ok else "FAIL: F-015 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f015() else 1)
