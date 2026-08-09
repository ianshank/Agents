#!/usr/bin/env python3
"""Live Phoenix smoke: prove tracing registers against a *running* collector.

Invoked by `scripts/run_all_e2e.ps1` as a Tier-D step.

Exit codes (see `_smoke_lib` for why 78 and not 2):
    0  -- a provider registered, a span was emitted, and the exporter drained
    78 -- PHOENIX_COLLECTOR_ENDPOINT unset; nothing attempted (SKIP)
    1  -- endpoint set but the collector was unreachable, or export failed (FAIL)

**Two checks, and both are load-bearing.** `configure_tracing` is contractually forbidden
from raising -- a telemetry problem must never break an evaluation run -- so it returns
`None` on every failure alike. Asserting the provider is non-`None` is therefore necessary.

It is not sufficient, and this was measured rather than assumed: OTLP export is
fire-and-forget, so with *nothing* listening `register()` still succeeds, `force_flush()`
reports no error, and the span is silently dropped. An earlier version of this file passed
against a dead collector for exactly that reason. Hence the reachability probe below --
without it, the step is green whether or not Phoenix exists, which is the same false-green
class the Tier-D repair exists to remove.
"""

from __future__ import annotations

import os
import os.path
import socket
import sys
from urllib.parse import urlparse

# Sibling-import bootstrap, matching scripts/validations/F_*.py: the runner invokes this as
# a plain script (`python scripts/smokes/phoenix_smoke.py`), so there is no package context
# to hang a relative import off. `scripts/smokes` is on `mypy_path` in pyproject.toml for
# the same reason `scripts/validations` is.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _smoke_lib import FAIL_EXIT_CODE, OK_EXIT_CODE, SKIP_EXIT_CODE, format_failure  # noqa: E402

ENV_ENDPOINT = "PHOENIX_COLLECTOR_ENDPOINT"

#: Seconds to wait for the collector's TCP port. Generous enough for a container that has
#: just started, short enough not to stall the tier.
CONNECT_TIMEOUT_SECONDS = 5

#: Port fallbacks when the endpoint URL omits an explicit one.
DEFAULT_PORTS = {"http": 80, "https": 443}

#: Project the smoke's spans group under, kept separate from real eval runs.
PROJECT_NAME = "e2e-smoke"
SPAN_NAME = "e2e-smoke-span"

_PREFIX = "phoenix-smoke"


def resolve_target(endpoint: str) -> tuple[str, int] | None:
    """Parse ``(host, port)`` out of *endpoint*, applying the scheme's default port.

    ``None`` when no host can be parsed. Split out from the socket call so the parsing and
    defaulting rules are testable without any I/O at all.
    """
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or DEFAULT_PORTS.get(parsed.scheme, 80)


def collector_reachable(endpoint: str) -> tuple[bool, str]:
    """Whether something accepts TCP connections at *endpoint*. Returns ``(ok, detail)``.

    A host that will not resolve, a refused connection, and a timeout are all "unreachable"
    -- each means an exported span goes nowhere.
    """
    target = resolve_target(endpoint)
    if target is None:
        return False, f"cannot parse a host out of {endpoint!r}"
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            return True, f"{host}:{port}"
    except OSError as exc:
        return False, f"{host}:{port} unreachable ({type(exc).__name__}: {exc})"


def main() -> int:
    endpoint = os.environ.get(ENV_ENDPOINT)
    if not endpoint:
        print(f"{_PREFIX}: SKIP, {ENV_ENDPOINT} unset")
        return SKIP_EXIT_CODE

    reachable, detail = collector_reachable(endpoint)
    if not reachable:
        print(f"{_PREFIX}: FAIL, {detail}. Start the collector before running Tier D.")
        return FAIL_EXIT_CODE

    try:
        from eval_harness.config.models import PhoenixConfig
        from eval_harness.phoenix_client import configure_tracing
    except ImportError as exc:
        print(f"{_PREFIX}: FAIL, cannot import client: {exc}")
        return FAIL_EXIT_CODE

    # auto_instrument=False: this exercises the collector round-trip, not the per-provider
    # OpenInference instrumentors. Leaving it on would make the result depend on which of
    # those optional extras happen to be installed.
    config = PhoenixConfig(enabled=True, tracing=True, project_name=PROJECT_NAME, auto_instrument=False)

    provider = configure_tracing(config)
    if provider is None:
        print(f"{_PREFIX}: FAIL, configure_tracing returned None for {endpoint}")
        return FAIL_EXIT_CODE

    try:
        tracer = provider.get_tracer(__name__)
        with tracer.start_as_current_span(SPAN_NAME) as span:
            span.set_attribute("smoke", True)
        # Drain deterministically rather than at interpreter exit. Note this does NOT
        # report export failures -- verified: with no collector listening it returns
        # cleanly and the span is dropped. That is why the reachability probe above is
        # required rather than optional.
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception as exc:
        print(format_failure(_PREFIX, exc))
        return FAIL_EXIT_CODE

    print(f"{_PREFIX}: OK, emitted '{SPAN_NAME}' to {endpoint} (project={PROJECT_NAME})")
    return OK_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
