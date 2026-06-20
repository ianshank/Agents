#!/usr/bin/env python3
"""Validation script for Feature F-014: Phase-2 — ReAct type-holdout, honest
instance/type holdout reported separately, and the confidence cross-check.

Deterministic and offline. Asserts the Phase-2 exit gates:
  1. instance-holdout (primary) and type-holdout (generalization) are reported as
     two SEPARATE numbers, never merged.
  2. The type-holdout carries an extrapolation-fraction caveat.
  3. A sub-power slice is flagged directional-only and cannot gate.
  4. The confidence cross-check returns a signed, significance-tested result
     (ablation vs a flow-type indicator, bootstrap CI on the AUROC delta).
"""
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("flow-protocol", "flow-corpus", "agent-core"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

from flow_corpus.config import CorpusConfig  # noqa: E402
from flow_corpus.crosscheck import CrossCheckRow, confidence_cross_check  # noqa: E402
from flow_corpus.holdout import HoldoutManager, Sample, samples_from_run  # noqa: E402
from flow_corpus.oracles import PropertyOracle  # noqa: E402
from flow_corpus.policy import MockPolicy  # noqa: E402
from flow_corpus.specimens import BaselineSpecimen, MCTSSpecimen, ReActSpecimen  # noqa: E402
from flow_corpus.suites.sdlc import build_sdlc_suite  # noqa: E402
from flow_corpus.validation import brier_reliability, run_suite  # noqa: E402


def validate_f014() -> bool:
    cfg = CorpusConfig(declared_n_per_domain=200, power_min_sample=40)
    suite = build_sdlc_suite(cfg, seed=11)
    oracle = PropertyOracle()

    def samples(spec) -> list[Sample]:
        return samples_from_run(run_suite(spec, suite, oracle, cfg, seed=4))

    by_type = {
        "baseline": samples(BaselineSpecimen(MockPolicy(0.7, 1.0))),
        "mcts": samples(MCTSSpecimen(MockPolicy(0.7, 1.0), n_rollouts=5)),
        "react": samples(ReActSpecimen(MockPolicy(0.7, 1.0), max_steps=3)),  # type-holdout
    }

    checks: dict[str, bool] = {}

    report = HoldoutManager(cfg, seed=7).evaluate(by_type, held_out_type="react")
    checks["instance- and type-holdout reported separately"] = (
        report.instance_holdout.reliability is not None
        and report.type_holdout.reliability is not None
        and report.instance_holdout is not report.type_holdout
    )
    checks["type-holdout carries extrapolation caveat"] = (
        0.0 <= report.extrapolation_fraction <= 1.0 and report.seen_support is not None
    )

    # Sub-power slice -> directional only (cannot gate).
    tiny = brier_reliability([0.5, 0.6, 0.4], [1, 0, 1], cfg)
    checks["sub-power slice is directional-only (cannot gate)"] = (
        tiny.directional_only and not tiny.passes
    )

    # Confidence cross-check: informative confidence beats the flow-type indicator.
    rng = random.Random(0)
    rows = []
    for i in range(400):
        ftype = "baseline" if i % 2 == 0 else "mcts"
        p = rng.random()
        rows.append(
            CrossCheckRow(
                flow_type=ftype,
                instance_id=f"i{i}",
                confidence=p,
                outcome=1 if rng.random() < p else 0,
            )
        )
    cc = confidence_cross_check(rows, cfg, seed=2, n_resamples=500)
    checks["confidence cross-check is signed + significance-tested"] = (
        cc.delta_ci is not None
        and cc.auroc_confidence is not None
        and cc.auroc_flow_indicator is not None
        and cc.confidence_adds_signal is True
    )

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-014 validation passed." if ok else "FAIL: F-014 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f014() else 1)
