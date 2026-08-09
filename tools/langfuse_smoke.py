#!/usr/bin/env python3
"""Live Langfuse smoke: prove the real SDK can reach the configured backend.

Invoked by ``scripts/run_all_e2e.ps1`` as a Tier-D step. It is deliberately *not*
under ``scripts/``: Tier A measures ``--cov=scripts`` against an 85% floor
(``scripts/.coveragerc``), and a live-network script has no offline unit tests, so
placing it there would fail Tier A while fixing Tier D.

Exit codes (the runner maps these):
    0  -- a score was logged and flushed against the real backend
    78 -- EX_CONFIG: required credentials absent, nothing was attempted (SKIP)
    1  -- credentials present but the call failed (FAIL)

``78`` rather than ``2`` is load-bearing. ``2`` is what CPython returns for a
missing file and what ``argparse`` returns for a bad flag, so a runner that maps
2->SKIP cannot distinguish "no credentials" from "this script is broken" -- which
is precisely how the previous Tier D reported green while invoking scripts that
did not exist.

**The non-vacuous check.** ``log_score`` and ``flush`` are fire-and-forget: the SDK
reports transport failures on its own logger and returns normally. Measured, not
assumed -- an earlier version of this script printed OK and exited 0 while the SDK
was emitting "Unexpected error occurred" for every call. So the actual verification
is ``Langfuse.auth_check()``, which performs a real authenticated round-trip and
raises or returns False; the score write is then a second, weaker signal.

No credential value is ever logged, including at debug level.
"""

from __future__ import annotations

import os
import sys
import uuid

EX_CONFIG = 78


#: TLS-intercepting corporate proxies present a CA that ``certifi`` does not carry, so
#: the SDK's httpx client fails with CERTIFICATE_VERIFY_FAILED even though the host
#: itself trusts the issuer. ``truststore`` routes verification through the OS trust
#: store, which is stricter than the alternatives people reach for (disabling
#: verification, or pinning a bundle by hand) -- it still verifies, just against the
#: certificates the machine is actually configured to trust. Optional: absent, we fall
#: through to certifi and surface an actionable message if that fails.
def _use_os_trust_store() -> bool:
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


REQUIRED_ENV = ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL")

#: Score name written by this smoke. Kept distinct from any real eval metric so the
#: rows it creates are trivially filterable in the Langfuse UI.
SCORE_NAME = "e2e_smoke"


def main() -> int:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        # Names only -- never values.
        print(f"langfuse-smoke: SKIP, unset: {', '.join(missing)}")
        return EX_CONFIG

    os_trust = _use_os_trust_store()

    try:
        from langfuse import Langfuse

        from eval_harness.langfuse_client import SDKLangfuseClient
    except ImportError as exc:
        print(f"langfuse-smoke: FAIL, cannot import client: {exc}")
        return 1

    # The real verification: an authenticated round-trip that reports its own failure.
    try:
        if not Langfuse().auth_check():
            print("langfuse-smoke: FAIL, auth_check() returned False (credentials rejected)")
            return 1
    except Exception as exc:
        hint = ""
        if "CERTIFICATE_VERIFY" in str(exc) and not os_trust:
            hint = " -- TLS verification failed against certifi; `pip install truststore` to use the OS trust store"
        print(f"langfuse-smoke: FAIL, auth_check {type(exc).__name__}: {exc}{hint}")
        return 1

    run_id = f"e2e-smoke-{uuid.uuid4().hex[:12]}"
    try:
        client = SDKLangfuseClient()
        client.log_score(
            run_id=run_id,
            item_id="smoke-item",
            name=SCORE_NAME,
            value=1.0,
            comment="run_all_e2e.ps1 Tier-D connectivity smoke",
        )
        client.flush()
    except Exception as exc:  # any failure here is a FAIL; report the type, not a traceback
        print(f"langfuse-smoke: FAIL, {type(exc).__name__}: {exc}")
        return 1

    # Host, not credentials. Confirms which backend was actually reached.
    print(f"langfuse-smoke: OK, logged '{SCORE_NAME}' for run {run_id} to {os.environ['LANGFUSE_BASE_URL']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
