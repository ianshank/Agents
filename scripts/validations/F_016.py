#!/usr/bin/env python3
"""Validation script for Feature F-016: behavioral-regression detector.

Deterministic and offline. Asserts the F-016 exit gates:
  1. A run is deterministic (byte-identical ``to_dict()`` for a fixed ``(BRConfig, seed)``)
     and offline (no network is touched on this path).
  2. An unvalidated judge (κ below threshold / below power) is advisory only — cannot gate.
  3. The detector separates a known-regression arm from a known-null arm (canary), and
     surfaces a can't-tell bucket on the null run.
  4. The gate fails safe to ESCALATE when the apparatus is untrusted; HOLDs a real
     regression; SHIPs only validated, separable, below-risk changes.
"""

import json
import os
import socket
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("flow-protocol", "flow-corpus", "agent-core", "behavioral-regression"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

from behavioral_regression import BRConfig, run_pipeline  # noqa: E402
from behavioral_regression.canary import CanaryReport, run_canary  # noqa: E402
from behavioral_regression.detector import RegressionEstimate  # noqa: E402
from behavioral_regression.gate import ShipDecision, decide_ship  # noqa: E402
from flow_corpus.oracles.kappa_gate import KappaReport  # noqa: E402
from flow_corpus.validation.resampling import BootstrapCI  # noqa: E402


def _estimate(*, point, low, high, p_regression, cant_tell):
    ci = BootstrapCI(point=point, low=low, high=high, n_resamples=100)
    return RegressionEstimate(
        p_regression=p_regression,
        wilson_low=0.0,
        wilson_high=1.0,
        delta_ci=ci,
        brier=0.1,
        reliability=0.05,
        n_determinate=200,
        cant_tell=cant_tell,
    )


def _kappa(may_gate):
    return KappaReport(
        kappa=0.9 if may_gate else 0.1,
        n_codeterminate=200,
        n_total=200,
        directional_only=not may_gate,
        may_gate=may_gate,
    )


def _canary(separated):
    return CanaryReport(regressed_p=0.8, null_p=0.4, margin=0.4, separated=separated)


def validate_f016() -> bool:
    checks: dict[str, bool] = {}
    cfg = BRConfig(n_pairs=300)

    # 1. Determinism (byte-identical) + offline (block sockets and still run).
    a = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    real_socket = socket.socket
    socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
    try:
        b = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    finally:
        socket.socket = real_socket
    checks["deterministic + offline run"] = a == b

    # 2. Unvalidated judge cannot gate.
    ok_est = _estimate(point=0.3, low=0.1, high=0.5, p_regression=0.8, cant_tell=False)
    checks["unvalidated judge => ESCALATE"] = (
        decide_ship(ok_est, _kappa(False), _canary(True), cfg) is ShipDecision.ESCALATE
    )

    # 3. Canary separation + can't-tell on the null run.
    can = run_canary(cfg, seed=7)
    null_run = run_pipeline(BRConfig(n_pairs=400), seed=7)  # v1 == v2 => null
    checks["canary separates known regression from null"] = (
        can.regressed_p > can.null_p and can.separated
    )
    checks["null run reports can't-tell"] = null_run.estimate.cant_tell

    # 4. Gate truth table: fail-safe, HOLD, SHIP.
    checks["canary not separated => ESCALATE"] = (
        decide_ship(ok_est, _kappa(True), _canary(False), cfg) is ShipDecision.ESCALATE
    )
    checks["real regression => HOLD"] = (
        decide_ship(ok_est, _kappa(True), _canary(True), cfg) is ShipDecision.HOLD
    )
    safe_est = _estimate(point=-0.2, low=-0.4, high=-0.05, p_regression=0.2, cant_tell=False)
    checks["validated, separable, below-risk => SHIP"] = (
        decide_ship(safe_est, _kappa(True), _canary(True), cfg) is ShipDecision.SHIP
    )

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-016 validation passed." if ok else "FAIL: F-016 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f016() else 1)
