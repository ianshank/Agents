"""Raw probe observables and their crash-safe JSONL persistence.

An observable is evidence, never a judgment: probes record what an operation DID
(status, latency, artifact ids, stderr); only the human-signed rubric turns those
into marks (spec scoring rule 1). The JSONL reader is strict — a malformed evidence
line is an error, never silently skipped (fail-safe-to-escalate, spec invariant 5).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

OP_STATUSES = ("ok", "error", "unsupported", "timeout")


class ObservableError(ValueError):
    """Raised for malformed observable records or evidence files."""


@dataclass(frozen=True)
class OpOutcome:
    """What a single backend operation did, as observed at the SDK/API boundary."""

    operation: str
    status: str
    latency_ms: float
    artifact_ids: tuple[str, ...] = ()
    response_excerpt: str = ""
    stderr: str = ""
    retries: int = 0

    def __post_init__(self) -> None:
        if self.status not in OP_STATUSES:
            raise ObservableError(f"status must be one of {OP_STATUSES}, got {self.status!r}")
        if self.latency_ms < 0:
            raise ObservableError(f"latency_ms must be >= 0, got {self.latency_ms}")


@dataclass(frozen=True)
class Observable:
    """An ``OpOutcome`` in context: which probe/cell/backend/repetition produced it."""

    probe_id: str
    cell_id: str
    backend: str
    rep_index: int
    ts_utc: str  # ISO-8601; supplied by the runner so records stay reproducible in tests
    outcome: OpOutcome
    extra: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        outcome = data.pop("outcome")
        outcome["artifact_ids"] = list(outcome["artifact_ids"])
        data["outcome"] = outcome
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Observable:
        try:
            raw_outcome = data["outcome"]
            if not isinstance(raw_outcome, dict):
                raise ObservableError("outcome must be a JSON object")
            outcome_fields = dict(raw_outcome)
            ids = outcome_fields.get("artifact_ids", ())
            if not isinstance(ids, (list, tuple)):
                raise ObservableError("artifact_ids must be a list")
            outcome_fields["artifact_ids"] = tuple(str(item) for item in ids)
            outcome = OpOutcome(**outcome_fields)
            rep_index = data["rep_index"]
            if not isinstance(rep_index, int):
                raise ObservableError("rep_index must be an integer")
            raw_extra = data.get("extra", {})
            if not isinstance(raw_extra, dict):
                raise ObservableError("extra must be a JSON object")
            return cls(
                probe_id=str(data["probe_id"]),
                cell_id=str(data["cell_id"]),
                backend=str(data["backend"]),
                rep_index=rep_index,
                ts_utc=str(data["ts_utc"]),
                outcome=outcome,
                extra=dict(raw_extra),
            )
        except (KeyError, TypeError, ObservableError) as exc:
            raise ObservableError(f"malformed observable record: {exc}") from exc


class ObservableLog:
    """Append-only JSONL evidence log; every append flushes so a crash loses nothing."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, observable: Observable) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(observable.to_dict(), sort_keys=True) + "\n")
            handle.flush()

    def read_all(self) -> list[Observable]:
        return list(self.iter_records())

    def iter_records(self) -> Iterator[Observable]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ObservableError(f"{self.path}:{line_number} is not valid JSON: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ObservableError(f"{self.path}:{line_number} must be a JSON object")
                yield Observable.from_dict(payload)
