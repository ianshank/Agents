"""Proxy extractors — the pluggable signals a proxy-correlation report measures.

Separated from :mod:`agent_core.proxy_eval` so adding a proxy never touches the analysis
code, and so each file stays inside the repo's 500-line budget.

A proxy answers "what did a cheap signal predict for this change?". Returning ``None``
means the proxy has nothing to say and the change is dropped from that proxy's dataset —
never silently coerced to a number, which would fabricate a correlation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .outcome_store import LabelSource, OutcomeRecord

# Passive label sources mapped to the outcome they predict. TIMEOUT_CLEAN is optimistic by
# construction (nothing was observed within the window, which is weak evidence of success),
# which is precisely why it is a *proxy* here and never an authoritative label.
_PASSIVE_PREDICTION: dict[str, float] = {
    LabelSource.REVERT.value: 0.0,
    LabelSource.CI_FAILURE.value: 0.0,
    LabelSource.TIMEOUT_CLEAN.value: 1.0,
}


@runtime_checkable
class ProxyExtractor(Protocol):
    """Turns every record a change accumulated into one proxy value, or ``None``.

    ``None`` means "this proxy has nothing to say about this change" and drops the change
    from that proxy's dataset — never silently coerced to zero, which would fabricate a
    correlation.
    """

    @property
    def name(self) -> str: ...

    def value(self, change_id: str, records: Sequence[OutcomeRecord]) -> float | None: ...


@dataclass(frozen=True)
class RawConfidenceProxy:
    """The agent's proxy confidence — the baseline every other proxy must beat.

    This is the signal the gate's calibrator already consumes, so its *conditional*
    correlation is the number that says whether PPI can help the gate itself.
    """

    name: str = "raw_confidence"

    def value(self, change_id: str, records: Sequence[OutcomeRecord]) -> float | None:
        for r in records:
            if r.label_source != LabelSource.HUMAN_AUDIT.value:
                return r.raw_confidence
        return records[0].raw_confidence if records else None


@dataclass(frozen=True)
class PassiveLabelProxy:
    """Mechanical outcome signals (revert / CI failure / clean timeout) as a proxy.

    Collected on *every* merge by the labeller and orthogonal to the confidence bin, so
    unlike confidence it can retain variance on a gated subset.
    """

    name: str = "passive_label"

    def value(self, change_id: str, records: Sequence[OutcomeRecord]) -> float | None:
        for r in records:
            if r.label_source in _PASSIVE_PREDICTION:
                return _PASSIVE_PREDICTION[r.label_source]
        return None


@dataclass(frozen=True)
class MappingProxy:
    """Externally-computed scores keyed by ``change_id``.

    The seam for any proxy this package must not depend on — an LLM judge, a static
    analyser, a human triage score. Compute elsewhere, hand the mapping in.
    """

    name: str
    scores: Mapping[str, float]

    def value(self, change_id: str, records: Sequence[OutcomeRecord]) -> float | None:
        v = self.scores.get(change_id)
        return None if v is None or not math.isfinite(v) else float(v)
