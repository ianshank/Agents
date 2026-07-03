#!/usr/bin/env python3
"""Validation script for Feature F-011: flow_protocol contract + structural airgap.

Checks, all deterministic:
  1. flow_protocol is importable and FlowResult/OracleResult round-trip via JSON.
  2. The drift gate passes against the manifest with the new components (exit 0).
  3. NEGATIVE TEST (the gate must fire): a throwaway flow_corpus module that imports
     eval_harness makes drift_check.py exit 1. A static "manifest has no edge" check
     would be insufficient — we prove the guard actually trips, then remove the fixture.
"""

import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(PROJECT_ROOT, "skills", "architecture-drift-guard")
DRIFT_CHECK = os.path.join(SKILL_DIR, "scripts", "drift_check.py")
MANIFEST = os.path.join(PROJECT_ROOT, "architecture.yaml")
GRIMP_CACHE = os.path.join(PROJECT_ROOT, ".grimp_cache")
PROBE = os.path.join(PROJECT_ROOT, "flow-corpus", "flow_corpus", "_airgap_probe.py")

sys.path.insert(0, os.path.join(PROJECT_ROOT, "flow-protocol"))


def _drift_exit() -> int:
    # Clear grimp's on-disk cache before each run: this negative test adds/removes a
    # source file between invocations, and a stale cache would make the probe run miss
    # the new edge (or the clean run see a removed one). A fresh parse each time makes
    # the airgap check hermetic and deterministic across environments.
    shutil.rmtree(GRIMP_CACHE, ignore_errors=True)
    res = subprocess.run(
        [sys.executable, DRIFT_CHECK, "--manifest", MANIFEST],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return res.returncode


def _contract_roundtrips() -> bool:
    from flow_protocol import FlowResult, OracleResult

    fr = FlowResult(instance_id="i1", flow_type="baseline", agent_version="v0", domain="sdlc")
    orc = OracleResult(instance_id="i1", verdict=None, oracle_tier="property", oracle_id="o1")
    return (
        FlowResult.model_validate_json(fr.model_dump_json()) == fr
        and OracleResult.model_validate_json(orc.model_dump_json()) == orc
        and orc.is_indeterminate
        and fr.raw_confidence is None  # optional: outcome-only flows need not fabricate one
    )


def validate_f011() -> bool:
    checks: dict[str, bool] = {}

    checks["flow_protocol contract round-trips"] = _contract_roundtrips()
    checks["drift gate passes clean (exit 0)"] = _drift_exit() == 0

    # Negative test: prove the airgap guard actually fires.
    negative_ok = False
    try:
        with open(PROBE, "w", encoding="utf-8") as fh:
            fh.write("from eval_harness import engine  # noqa: F401  (airgap probe)\n")
        negative_ok = _drift_exit() == 1
    finally:
        if os.path.exists(PROBE):
            os.remove(PROBE)
    checks["forbidden corpus->harness import trips the gate (exit 1)"] = negative_ok
    # And confirm it returns to clean once the probe is gone (no leaked state).
    checks["gate clean again after probe removed"] = _drift_exit() == 0

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-011 validation passed." if ok else "FAIL: F-011 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f011() else 1)
