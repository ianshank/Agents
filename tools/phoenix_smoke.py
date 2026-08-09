#!/usr/bin/env python3
"""Live Phoenix smoke: prove tracing registers against a running collector.

Invoked by ``scripts/run_all_e2e.ps1`` as a Tier-D step. See the sibling
``langfuse_smoke.py`` for why this lives in ``tools/`` and not ``scripts/``.

Exit codes:
    0  -- a tracer provider was registered and a span was emitted and flushed
    78 -- EX_CONFIG: PHOENIX_COLLECTOR_ENDPOINT unset, nothing attempted (SKIP)
    1  -- endpoint set but registration or export failed (FAIL)

**The non-vacuous checks -- both are necessary.** ``configure_tracing`` is
contractually forbidden from raising (a telemetry problem must never break an
evaluation run), so it returns ``None`` on every failure. Asserting the provider is
non-``None`` is therefore the first check.

It is not sufficient. OTLP export is fire-and-forget: with *nothing* listening,
``register()`` still succeeds, ``force_flush()`` reports no error, and the span is
silently dropped -- measured, not assumed. So this also probes that something is
actually accepting connections at the endpoint first. Without that probe the step
passes whether or not a collector exists, which is the same class of false green
this whole Tier-D repair exists to remove.
"""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import urlparse

EX_CONFIG = 78

ENV_ENDPOINT = "PHOENIX_COLLECTOR_ENDPOINT"

#: Seconds to wait for the collector's TCP port. Generous enough for a container that
#: has just started, short enough not to stall the tier.
CONNECT_TIMEOUT_SECONDS = 5

#: Fallbacks when the endpoint URL omits an explicit port.
DEFAULT_PORTS = {"http": 80, "https": 443}

#: Project the smoke's spans are grouped under, kept separate from real eval runs.
PROJECT_NAME = "e2e-smoke"
SPAN_NAME = "e2e-smoke-span"


def _collector_reachable(endpoint: str) -> tuple[bool, str]:
    """Whether something is accepting TCP connections at *endpoint*.

    Returns ``(ok, detail)``. A hostname that will not resolve, a refused connection,
    or a timeout all count as unreachable -- any of them means an exported span goes
    nowhere.
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if not host:
        return False, f"cannot parse a host out of {endpoint!r}"
    port = parsed.port or DEFAULT_PORTS.get(parsed.scheme, 80)
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_SECONDS):
            return True, f"{host}:{port}"
    except OSError as exc:
        return False, f"{host}:{port} unreachable ({type(exc).__name__}: {exc})"


def main() -> int:
    endpoint = os.environ.get(ENV_ENDPOINT)
    if not endpoint:
        print(f"phoenix-smoke: SKIP, {ENV_ENDPOINT} unset")
        return EX_CONFIG

    reachable, detail = _collector_reachable(endpoint)
    if not reachable:
        print(f"phoenix-smoke: FAIL, {detail}. Start the collector before running Tier D.")
        return 1

    try:
        from eval_harness.config.models import PhoenixConfig
        from eval_harness.phoenix_client import configure_tracing
    except ImportError as exc:
        print(f"phoenix-smoke: FAIL, cannot import client: {exc}")
        return 1

    # auto_instrument=False: this smoke tests the collector round-trip, not the
    # per-provider OpenInference instrumentors, and leaving it on would make the
    # result depend on which of those extras happen to be installed.
    config = PhoenixConfig(enabled=True, tracing=True, project_name=PROJECT_NAME, auto_instrument=False)

    provider = configure_tracing(config)
    if provider is None:
        print(f"phoenix-smoke: FAIL, configure_tracing returned None for {endpoint} (collector not reachable?)")
        return 1

    try:
        tracer = provider.get_tracer(__name__)
        with tracer.start_as_current_span(SPAN_NAME) as span:
            span.set_attribute("smoke", True)
        # Drain the batch exporter deterministically rather than at interpreter exit.
        # Note this does NOT report export failures -- verified: with no collector
        # listening it returns cleanly and the span is dropped. That is precisely why
        # the reachability probe above is required, not optional.
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception as exc:  # any failure here is a FAIL; report the type, not a traceback
        print(f"phoenix-smoke: FAIL, {type(exc).__name__}: {exc}")
        return 1

    print(f"phoenix-smoke: OK, emitted '{SPAN_NAME}' to {endpoint} (project={PROJECT_NAME})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
