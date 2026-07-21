"""Shared dispatch-table base for SDK probe clients.

Every backend client is a mapping ``operation -> _op_* method``; each method is a thin
raw-SDK/REST call returning an ``OpDraft``. This base owns the invariants: latency is
measured around every call, exceptions become ``error`` observables (never crashes), and
unknown operations return ``unsupported`` — which is EVIDENCE for an absent capability,
not a failure of the probe layer.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from backend_validation.observables import OpOutcome


@dataclass(frozen=True)
class OpDraft:
    """What an ``_op_*`` method reports; the base adds operation name and latency."""

    status: str = "ok"
    artifact_ids: tuple[str, ...] = ()
    response_excerpt: str = ""
    stderr: str = ""


OpHandler = Callable[[Mapping[str, object]], OpDraft]


class DispatchProbeClient:
    """Base class implementing ``ProbeClient.execute`` over a dispatch table."""

    backend_id: str = "base"
    idempotent_operations: frozenset[str] = frozenset()

    def _ops(self) -> Mapping[str, OpHandler]:
        raise NotImplementedError

    def execute(self, operation: str, payload: Mapping[str, object]) -> OpOutcome:
        handler = self._ops().get(operation)
        started = time.perf_counter()
        if handler is None:
            return OpOutcome(
                operation=operation,
                status="unsupported",
                latency_ms=0.0,
                stderr=f"{self.backend_id} client has no handler for this operation",
            )
        try:
            draft = handler(payload)
        except Exception as exc:  # honest evidence beats a crashed run (fail-safe)
            latency_ms = (time.perf_counter() - started) * 1000.0
            return OpOutcome(
                operation=operation,
                status="error",
                latency_ms=latency_ms,
                stderr=f"{type(exc).__name__}: {exc}",
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        return OpOutcome(
            operation=operation,
            status=draft.status,
            latency_ms=latency_ms,
            artifact_ids=draft.artifact_ids,
            response_excerpt=draft.response_excerpt,
            stderr=draft.stderr,
        )

    def close(self) -> None:  # subclasses override when the SDK holds resources
        return None
