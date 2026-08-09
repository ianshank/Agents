"""Shared helpers for the Tier-D live-integration smoke scripts.

These scripts live under `scripts/` rather than a `tools/` directory on purpose. `tools/`
would sit outside *three* separate gates at once — `--cov=scripts` (the 85% floor in
`scripts/.coveragerc`), `mypy scripts` (`scripts/quality-gate.sh`), and
`check_charter_invariants._MISSION_DIRS` — so new production code there is unmeasured,
untyped and unscanned by default. Putting them here earns all three with no config change.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence

#: Exit code meaning "this integration is not configured -- treat as SKIP, not a failure".
#:
#: Deliberately **not** 2. CPython exits 2 for a missing script file and `argparse` exits 2
#: for a bad flag, so a runner mapping 2 -> SKIP cannot tell "not configured" from "this
#: step is broken" -- which is exactly how Tier D reported green for years while invoking
#: two scripts that did not exist. 78 is `EX_CONFIG` from sysexits(3); it is hardcoded
#: rather than taken from `os.EX_CONFIG` because that constant is POSIX-only and these
#: scripts must behave identically on Windows.
#:
#: `scripts/run_all_e2e.ps1` mirrors this value in `$SkipExitCode`. The two cannot be
#: shared at runtime across the language boundary, so `tests/test_smoke_lib.py` asserts
#: they agree — the same drift-guard posture as `check_skill_script_drift.py`.
SKIP_EXIT_CODE = 78

#: Exit code for "configured, attempted, and it did not work".
FAIL_EXIT_CODE = 1

#: Exit code for a verified round-trip.
OK_EXIT_CODE = 0


def missing_env(names: Sequence[str]) -> list[str]:
    """Which of *names* are absent or empty in the environment, in the given order."""
    return [name for name in names if not os.environ.get(name)]


def use_os_trust_store() -> bool:
    """Route TLS verification through the OS trust store if `truststore` is available.

    A TLS-intercepting proxy presents a CA that `certifi` does not carry, so SDKs verifying
    against certifi fail with CERTIFICATE_VERIFY_FAILED even on a host that trusts the
    issuer. `truststore` fixes that *without weakening anything* — it still verifies, just
    against the certificates the machine is actually configured to trust, which is why this
    is preferable to the usual workarounds (disabling verification, or hand-pinning a
    bundle).

    Returns whether the injection happened, so callers can tailor their error hint.
    """
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


def format_missing(prefix: str, names: Iterable[str]) -> str:
    """SKIP line naming the unset variables. Names only — never values."""
    return f"{prefix}: SKIP, unset: {', '.join(names)}"


def format_failure(prefix: str, exc: BaseException, hint: str = "") -> str:
    """FAIL line carrying the exception type and message, plus an optional actionable hint.

    Deliberately not a traceback: these run as one step in an aggregated report, where a
    single readable line is worth more than a stack the reader has to scroll past.
    """
    return f"{prefix}: FAIL, {type(exc).__name__}: {exc}{hint}"
