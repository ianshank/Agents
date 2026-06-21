#!/usr/bin/env python3
"""Validation script for Feature F-013: Phase-1 corpus — baseline+MCTS, SDLC oracle,
canary, oracle κ-gate, version keyer.

Deterministic and offline. Asserts the Phase-1 exit gates:
  1. The SDLC suite ships the DECLARED N instances (power is declared, not guessed).
  2. The mandatory baseline control is registered, alongside MCTS.
  3. The version key excludes the task and includes the config (re-key / no-task-rekey).
  4. The property oracle's indeterminate rate is within the derived cap.
  5. Brier reliability is computed via the Murphy decomposition (primary metric path).
  6. The discrimination canary separates gold from no-op by the configured margin.
  7. The oracle κ-gate blocks a disagreeing oracle and passes an agreeing one
     (co-determinate pairs only, power-aware).
"""
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("flow-protocol", "flow-corpus", "agent-core"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

from flow_corpus.canary import GoldSpecimen, NoOpSpecimen, canary_separation  # noqa: E402
from flow_corpus.config import CorpusConfig  # noqa: E402
from flow_corpus.keying import version_key  # noqa: E402
from flow_corpus.oracles import PropertyOracle, validate_oracle  # noqa: E402
from flow_corpus.policy import MockPolicy  # noqa: E402
from flow_corpus.specimens import SPECIMENS, BaselineSpecimen, MCTSSpecimen  # noqa: E402
from flow_corpus.suites.sdlc import build_sdlc_suite, load_suite  # noqa: E402
from flow_corpus.validation import run_suite  # noqa: E402


def _outcomes(spec, suite, oracle) -> list[int]:
    rng = random.Random(0)
    return [1 if oracle.judge(i, spec.run(i, rng)).verdict else 0 for i in suite.instances]


def validate_f013() -> bool:
    cfg = CorpusConfig(declared_n_per_domain=200, power_min_sample=100)
    suite = build_sdlc_suite(cfg)
    oracle = PropertyOracle()
    checks: dict[str, bool] = {}

    # 1. Declared N — generated suite and committed snapshot agree on size.
    snapshot = load_suite()
    checks["suite ships declared N=200 instances"] = (
        len(suite) == cfg.declared_n_per_domain and len(snapshot) == cfg.declared_n_per_domain
    )

    # 2. Mandatory baseline control registered, with MCTS.
    checks["baseline control + mcts registered"] = (
        SPECIMENS.get("baseline") is BaselineSpecimen
        and SPECIMENS.get("mcts") is MCTSSpecimen
    )

    # 3. Version keyer: task excluded, config included.
    k1 = version_key("mcts@1", {"skill": 0.7, "n_rollouts": 5})
    k1_reordered = version_key("mcts@1", {"n_rollouts": 5, "skill": 0.7})
    k_diff_cfg = version_key("mcts@1", {"skill": 0.7, "n_rollouts": 7})
    mcts = MCTSSpecimen(MockPolicy(skill=0.8), n_rollouts=5)
    r_a = mcts.run(suite.instances[0], random.Random(1))
    r_b = mcts.run(suite.instances[50], random.Random(1))
    checks["version key: order-independent + config-sensitive"] = (
        k1 == k1_reordered and k1 != k_diff_cfg
    )
    checks["version key: task does NOT re-key"] = r_a.agent_version == r_b.agent_version

    # 4 + 5. Run a well-calibrated baseline -> reliability via brier_decomposition, cap check.
    run = run_suite(BaselineSpecimen(MockPolicy(0.75, 1.0)), suite, oracle, cfg, seed=3)
    checks["indeterminate rate within derived cap"] = run.within_indeterminate_cap(cfg)
    checks["Brier reliability computed (primary metric, gating-eligible)"] = (
        run.reliability.reliability is not None and not run.reliability.directional_only
    )
    checks["outcomes keyed by (agent_version, domain)"] = all(
        rec.agent_version == run.agent_version and rec.domain == "sdlc"
        for rec in run.outcome_records
    ) and len(run.outcome_records) > 0

    # 6. Canary separation: gold vs no-op.
    sep = canary_separation(
        _outcomes(GoldSpecimen(), suite, oracle),
        _outcomes(NoOpSpecimen(), suite, oracle),
        cfg,
    )
    checks["canary separates gold from no-op"] = sep.separated and sep.margin >= cfg.min_canary_margin

    # 7. Oracle κ-gate: blocks disagreement, passes agreement (>= power_min_sample pairs).
    agree = [True, False, True, True, False] * 40  # 200 perfectly-agreeing pairs
    disagree_o = [True, False] * 100
    disagree_h = [False, True] * 100
    checks["oracle κ-gate passes an agreeing oracle"] = validate_oracle(agree, agree, cfg).passes
    checks["oracle κ-gate blocks a disagreeing oracle"] = (
        validate_oracle(disagree_o, disagree_h, cfg).passes is False
    )

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-013 validation passed." if ok else "FAIL: F-013 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f013() else 1)
