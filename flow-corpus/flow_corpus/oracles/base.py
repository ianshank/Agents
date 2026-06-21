"""Oracle protocol: judge a FlowResult against an instance, deterministically.

An oracle returns an :class:`flow_protocol.OracleResult` whose ``verdict`` is
``True``/``False`` or ``None`` (indeterminate — the oracle abstains, routing the
case to the audit queue rather than feeding the gate a guess).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from flow_protocol import FlowResult, OracleResult

from flow_corpus.suites.base import TaskInstance


@runtime_checkable
class Oracle(Protocol):
    oracle_id: str

    def judge(self, instance: TaskInstance, result: FlowResult) -> OracleResult:
        """Return a verdict for *result* on *instance* (None = indeterminate)."""
        ...
