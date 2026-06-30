#!/usr/bin/env python3
"""Validation script for Feature F-010: calibrated auto-merge gate.

Deterministic and dependency-light: imports the pure agent_core merge-gate
subsystem (adding agent-core/ to sys.path so no install is needed) and asserts
the safety invariants hold — mechanical failure REJECTs, protected paths
ESCALATE, the happy path AUTO_MERGEs, the exit-code contract is complete, and
protected auto-merge is off by default.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "agent-core"))

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from agent_core.audit_sampler import record_verdict  # noqa: E402
from agent_core.merge_gate import (  # noqa: E402
    CalibratorHealth,
    ChangeContext,
    GateDecision,
    GatePolicyConfig,
    decide,
)
from agent_core.merge_gate_ci import EXIT  # noqa: E402
from agent_core.merge_seed import seed_pending  # noqa: E402
from agent_core.outcome_store import LabelSource, OutcomeStore  # noqa: E402


class _Const:
    def predict(self, raw_score: float) -> float:
        return 0.99


def _seam_closes_audit_data_gap() -> bool:
    """The F-010 seam (ADR 0005): a merge-time pending record must let the audit
    sampler attach a HUMAN_AUDIT verdict that the gate's models can then read.
    Without seeding, record_verdict raises KeyError and tau stays None forever.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = OutcomeStore(Path(tmp) / "s.jsonl")
        # before seeding: nothing to resolve
        try:
            record_verdict(store, "c1", correct=True)
            return False  # should have raised KeyError
        except KeyError:
            pass
        # seeding writes a pending record (label=None); idempotent on retry
        rec = seed_pending(store, "c1", "core", 0.91)
        if rec is None or rec.label is not None:
            return False
        if seed_pending(store, "c1", "core", 0.91) is not None:
            return False  # second seed must be a no-op
        # after seeding: a human audit verdict resolves authoritatively
        audit = record_verdict(store, "c1", correct=True)
        return (
            audit.label is True
            and store.resolved()["c1"].label_source == LabelSource.HUMAN_AUDIT.value
        )


def validate_f010() -> bool:
    cfg = GatePolicyConfig()
    healthy = CalibratorHealth(n=2000, ece=0.02, auroc=0.9, bin_ci_width=0.05)
    cal = _Const()

    checks = {
        "mechanical failure REJECTs": (
            decide(ChangeContext(False, False, 0.99, "core"), cal, healthy, 0.5, 100, 100, cfg)
            == GateDecision.REJECT
        ),
        "protected paths ESCALATE": (
            decide(ChangeContext(True, True, 0.99, "core"), cal, healthy, 0.5, 100, 100, cfg)
            == GateDecision.ESCALATE
        ),
        "cold start ESCALATEs": (
            decide(ChangeContext(True, False, 0.99, "core"), None, None, None, 0, 0, cfg)
            == GateDecision.ESCALATE
        ),
        "happy path AUTO_MERGEs": (
            decide(ChangeContext(True, False, 0.99, "core"), cal, healthy, 0.5, 1000, 1000, cfg)
            == GateDecision.AUTO_MERGE
        ),
        "exit-code contract complete": set(EXIT.values()) == {0, 10, 20},
        "protected auto-merge off by default": cfg.protected_auto_merge is False,
        "merge-time seeding closes the audit-data seam": _seam_closes_audit_data_gap(),
    }
    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    if ok:
        print("OK: F-010 validation passed.")
    else:
        print("FAIL: F-010 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f010() else 1)
