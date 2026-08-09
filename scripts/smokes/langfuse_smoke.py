#!/usr/bin/env python3
"""Live Langfuse smoke: prove the real SDK can reach the configured backend.

Invoked by `scripts/run_all_e2e.ps1` as a Tier-D step.

Exit codes (see `_smoke_lib` for why 78 and not 2):
    0  -- an authenticated round-trip succeeded and a score was written
    78 -- required credentials absent; nothing attempted (SKIP)
    1  -- credentials present but the call failed (FAIL)

**The non-vacuous check.** `log_score` and `flush` are fire-and-forget: the SDK reports
transport failures on its own logger and returns normally. Measured, not assumed -- an
earlier version of this file printed OK and exited 0 while the SDK emitted "Unexpected
error occurred" on every call. So the real verification is `Langfuse.auth_check()`, which
performs an authenticated round-trip and either raises or returns False; the score write
is a second, weaker signal that the sink path also works.

No credential value is ever printed, at any level. `LANGFUSE_BASE_URL` is echoed on
success because it is a host, not a secret, and knowing which backend was reached is the
point of a smoke.
"""

from __future__ import annotations

import os
import os.path
import sys
import uuid

# Sibling-import bootstrap, matching scripts/validations/F_*.py: the runner invokes this as
# a plain script (`python scripts/smokes/langfuse_smoke.py`), so there is no package context
# to hang a relative import off. `scripts/smokes` is on `mypy_path` in pyproject.toml for
# the same reason `scripts/validations` is.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _smoke_lib import (  # noqa: E402
    FAIL_EXIT_CODE,
    OK_EXIT_CODE,
    SKIP_EXIT_CODE,
    format_failure,
    format_missing,
    missing_env,
    use_os_trust_store,
)

REQUIRED_ENV = ("LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL")

#: Score name written by this smoke. Distinct from any real eval metric so the rows it
#: creates are trivially filterable in the Langfuse UI.
SCORE_NAME = "e2e_smoke"

#: Appended when TLS verification fails and the OS trust store was not in play. The
#: Phoenix smoke needs no equivalent: it talks OTLP to a local collector and never
#: performs certificate verification.
_TLS_HINT = " -- TLS verification failed against certifi; `pip install truststore` to use the OS trust store"

_PREFIX = "langfuse-smoke"


def main() -> int:
    missing = missing_env(REQUIRED_ENV)
    if missing:
        print(format_missing(_PREFIX, missing))
        return SKIP_EXIT_CODE

    os_trust = use_os_trust_store()

    try:
        from langfuse import Langfuse

        from eval_harness.langfuse_client import SDKLangfuseClient
    except ImportError as exc:
        print(f"{_PREFIX}: FAIL, cannot import client: {exc}")
        return FAIL_EXIT_CODE

    # The real verification: a round-trip that reports its own failure.
    try:
        if not Langfuse().auth_check():
            print(f"{_PREFIX}: FAIL, auth_check() returned False (credentials rejected)")
            return FAIL_EXIT_CODE
    except Exception as exc:
        hint = _TLS_HINT if ("CERTIFICATE_VERIFY" in str(exc) and not os_trust) else ""
        print(format_failure(f"{_PREFIX} auth_check", exc, hint))
        return FAIL_EXIT_CODE

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
    except Exception as exc:
        print(format_failure(_PREFIX, exc))
        return FAIL_EXIT_CODE

    print(f"{_PREFIX}: OK, logged '{SCORE_NAME}' for run {run_id} to {os.environ['LANGFUSE_BASE_URL']}")
    return OK_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
