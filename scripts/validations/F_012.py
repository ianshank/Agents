#!/usr/bin/env python3
"""Validation script for Feature F-012: two-way version pin + forced-mismatch negative test.

The corpus pins the flow_protocol contract version and the agent_core (harness) version
it was built against. This validator asserts:
  1. verify_pins() passes when live versions match the pins (positive).
  2. A forced protocol mismatch raises PinMismatchError (the build FAILS on skew).
  3. A forced harness mismatch raises PinMismatchError.
The negative cases are the point: if a wrong pin passed, the skew tripwire would be dead.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for rel in ("flow-protocol", "flow-corpus", "agent-core"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, rel))

import flow_corpus.pinning as pinning  # noqa: E402
from flow_corpus.pinning import PinMismatchError, verify_pins  # noqa: E402


def _raises_mismatch(setup) -> bool:
    """Apply a monkeypatch-like mutation, assert verify_pins raises, then restore."""
    restore = setup()
    try:
        verify_pins()
        return False  # should have raised
    except PinMismatchError:
        return True
    finally:
        restore()


def validate_f012() -> bool:
    checks: dict[str, bool] = {}

    # 1. Positive: pins match live versions.
    try:
        report = verify_pins()
        checks["pins match live versions"] = report.ok
    except PinMismatchError:
        checks["pins match live versions"] = False

    # 2. Forced protocol mismatch FAILS.
    def _bad_protocol():
        original = pinning.PROTOCOL_VERSION
        pinning.PROTOCOL_VERSION = "9.9.9"
        return lambda: setattr(pinning, "PROTOCOL_VERSION", original)

    checks["forced protocol mismatch raises (build fails)"] = _raises_mismatch(_bad_protocol)

    # 3. Forced harness mismatch FAILS.
    def _bad_harness():
        original = pinning._live_harness_version
        pinning._live_harness_version = lambda: "9.9.9"
        return lambda: setattr(pinning, "_live_harness_version", original)

    checks["forced harness mismatch raises (build fails)"] = _raises_mismatch(_bad_harness)

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("OK: F-012 validation passed." if ok else "FAIL: F-012 validation failed.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if validate_f012() else 1)
