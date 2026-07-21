"""Probe transport clients: one narrow seam per backend, faked in tests, lazy in prod.

``ProbeClient`` is deliberately a probe TRANSPORT, not an eval abstraction — it executes a
named operation and reports what happened. It must never grow scoring/run semantics: a
unified backend abstraction is exactly what the harness does NOT have (L2's finding), and
inventing one here would contaminate the evidence (spec R4).

Construction follows the repo's braintrust-client triad: a ``Null*`` in-memory double for
tests and offline mode, an SDK wrapper built around an INJECTED handle, and a fail-safe
``build_client`` factory that lazy-imports the SDK and degrades loudly-but-safely.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend_validation.logging_util import get_logger
from backend_validation.observables import OpOutcome
from backend_validation.settings import BackendSpec, JudgeSpec

logger = get_logger(__name__)

INSTALL_HINTS = {
    "langfuse": "pip install -e '.[langfuse]'  (from experiments/backend-validation)",
    "opik": "pip install -e '.[opik]'  (from experiments/backend-validation)",
}

# Fallback per-operation timeout when no config value is threaded in (settings normally
# supplies settings.timeouts.op_seconds). Single source of truth for the two clients.
DEFAULT_OP_TIMEOUT_SECONDS = 30.0


class MissingCredentialsError(RuntimeError):
    """Required credential env vars are unset. NOT swallowed by ``build_client``: a live
    phase must turn this into a BLOCKED report naming the variables, never a Null client
    silently producing absent-looking evidence."""


@runtime_checkable
class ProbeClient(Protocol):
    """The whole client surface: execute one named operation, say what happened."""

    backend_id: str
    idempotent_operations: frozenset[str]

    def execute(self, operation: str, payload: Mapping[str, object]) -> OpOutcome: ...

    def close(self) -> None: ...


def unsupported(operation: str, reason: str = "operation not implemented by this client") -> OpOutcome:
    """The conservative outcome for an unknown operation — evidence for an absent mark."""
    return OpOutcome(operation=operation, status="unsupported", latency_ms=0.0, stderr=reason)


@dataclass
class NullProbeClient:
    """Recording double: scripted outcomes in, call log out. Never touches a network.

    ``script`` maps operation name to either an ``OpOutcome`` or a callable producing one
    from the payload; unscripted operations succeed with a synthetic artifact id so happy
    paths compose, unless ``default_status`` says otherwise.
    """

    backend_id: str = "null"
    script: Mapping[str, OpOutcome | Callable[[Mapping[str, object]], OpOutcome]] = field(default_factory=dict)
    default_status: str = "ok"
    idempotent_operations: frozenset[str] = frozenset()
    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def execute(self, operation: str, payload: Mapping[str, object]) -> OpOutcome:
        self.calls.append((operation, dict(payload)))
        scripted = self.script.get(operation)
        if callable(scripted):
            return scripted(payload)
        if scripted is not None:
            return scripted
        if self.default_status != "ok":
            return OpOutcome(operation=operation, status=self.default_status, latency_ms=0.0)
        return OpOutcome(
            operation=operation,
            status="ok",
            latency_ms=0.0,
            artifact_ids=(f"{self.backend_id}-{operation}-{len(self.calls)}",),
        )

    def close(self) -> None:  # the double holds no resources
        return None


def build_client(
    spec: BackendSpec,
    *,
    judge: JudgeSpec | None = None,
    enabled: bool = True,
    env: Mapping[str, str] | None = None,
    op_timeout: float | None = None,
) -> ProbeClient:
    """Fail-safe factory: real SDK client when possible, Null double otherwise.

    Mirrors ``eval_harness.braintrust_client.build_client``: disabled or SDK-missing means
    a Null client plus a loud log line — probes then record honest ``unsupported``/``error``
    observables instead of crashing the run. ``op_timeout`` (from
    ``settings.timeouts.op_seconds``) is threaded into the client so the configured
    per-operation timeout actually governs REST/SDK calls instead of a hardcoded default.
    """
    if not enabled:
        logger.info("client for %s disabled; using NullProbeClient", spec.id)
        return NullProbeClient(backend_id=spec.id)
    try:
        if spec.id == "langfuse":
            from backend_validation.clients.langfuse import LangfuseProbeClient

            return LangfuseProbeClient.from_spec(spec, judge=judge, env=env, op_timeout=op_timeout)
        if spec.id == "opik":
            from backend_validation.clients.opik import OpikProbeClient

            return OpikProbeClient.from_spec(spec, judge=judge, env=env, op_timeout=op_timeout)
    except ImportError as exc:
        hint = INSTALL_HINTS.get(spec.id, "install the backend SDK extra")
        logger.warning("SDK for %s not importable (%s); using NullProbeClient. Hint: %s", spec.id, exc, hint)
        return NullProbeClient(backend_id=spec.id)
    except MissingCredentialsError:
        raise  # a live-phase precondition; callers convert it to BLOCKED, not to a Null client
    except Exception as exc:  # other init failure is evidence, not a crash (fail-safe)
        logger.warning("client init for %s failed (%s); using NullProbeClient", spec.id, exc)
        return NullProbeClient(backend_id=spec.id)
    logger.warning("no client implementation for backend %s; using NullProbeClient", spec.id)
    return NullProbeClient(backend_id=spec.id)
