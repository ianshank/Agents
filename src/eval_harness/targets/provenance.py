"""Provenance-recording retrieval target wrapper (synthetic requirements scope).

Implements ``openspec/changes/add-requirements-gen-eval-matrix`` task 1. The wrapper
performs retrieval for an item's declared evidence sources, records one evidence record
per source, and attaches them to the output's metadata under
``core.types.REQUIREMENTS_EVIDENCE_KEY`` — the target-produces / scorer-reads seam from
ADR 0043, so the scorers stay pure and deterministic.

**The record is honest about pinnability.** A source fetched through a revision-scoped
reference carries ``content_sha256`` over the bytes that reference returned. A source
that cannot be pinned (a continuously re-crawled index, an unversioned blob) is recorded
with ``pinnable: false`` and carries **no** ``content_sha256`` key at all — omitting the
field is the point: a reader must not be able to mistake a churn-prone hash for a
verified one (spec: "Only obtainable metadata is recorded").

Live fetchers (Google Drive ``Revision.exportLinks``, Context7) are SDK-optional
adapters behind the ``EvidenceStore`` protocol; the offline path and the synthetic
corpus use an in-memory store. The verification pass (``verify_provenance``) re-fetches
every recorded reference and reports a mismatch as a *provenance failure*, a class
distinct from a scoring failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeAlias, runtime_checkable

from ..core._paths import DATA_ROOT_ENV, resolve_confined_path
from ..core.interfaces import TargetRunner
from ..core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem, TargetOutput
from ..plugins import TARGETS

logger = logging.getLogger(__name__)

#: Reference kinds that pin content to a version (a re-fetch returns the same bytes).
PINNABLE_KINDS: frozenset[str] = frozenset({"revision_export_link", "content_addressed"})

#: The DI seam for "now". Named rather than left as ``Any`` so a caller injecting a fixed
#: clock is type-checked at the call site; mirrors ``agent_core.protocols.Clock`` in shape
#: without importing it (that package is not a dependency of the harness).
RetrievalClock: TypeAlias = Callable[[], object]


@runtime_checkable
class EvidenceStore(Protocol):
    """Where evidence bytes come from. The synthetic corpus's store is in-memory; live
    adapters (Drive, Context7) implement the same single-call surface.

    Verification is deliberately *not* a store method: ``verify_provenance`` re-fetches
    through ``fetch`` and compares hashes itself, so a store cannot self-certify content
    it has already drifted away from.
    """

    def fetch(self, source_id: str, reference: dict[str, Any]) -> bytes:
        """Return the bytes *reference* resolves to for *source_id*."""
        ...


@dataclass(frozen=True)
class MappingEvidenceStore:
    """An in-memory store for the offline suite and the synthetic corpus."""

    contents: dict[str, bytes] = field(default_factory=dict)

    def fetch(self, source_id: str, reference: dict[str, Any]) -> bytes:
        try:
            return self.contents[source_id]
        except KeyError as exc:
            logger.debug("Evidence source %r not found in store", source_id)
            raise KeyError(f"evidence source {source_id!r} is not in the store") from exc


def load_store_file(path: str | Path) -> MappingEvidenceStore:
    """Build a store from a JSON ``{source_id: content}`` mapping on disk.

    A config naming a file is a config-driven filesystem read, so it goes through the
    same ``DATA_ROOT`` confinement every dataset read uses (ADR 0039's sibling rule) —
    an evidence store is dataset-shaped input and must not be the one read that escapes.
    """
    resolved = resolve_confined_path(
        path, root_env_var=DATA_ROOT_ENV, description="evidence store path", must_exist=True
    )
    payload: Any = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence store {resolved} must be a JSON object of source_id -> content")
    logger.debug("Loaded %d evidence sources from %s", len(payload), resolved)
    return MappingEvidenceStore(contents={str(k): str(v).encode("utf-8") for k, v in payload.items()})


def build_evidence_record(
    source_type: str,
    source_id: str,
    reference: dict[str, Any],
    content: bytes,
    *,
    retrieved_at: str,
) -> dict[str, Any]:
    """One evidence record. Unpinnable references carry no ``content_sha256`` key."""
    record: dict[str, Any] = {
        "source_type": source_type,
        "source_id": source_id,
        "reference": reference,
        "pinnable": reference.get("kind") in PINNABLE_KINDS,
        "retrieved_at": retrieved_at,
    }
    if record["pinnable"]:
        record["content_sha256"] = hashlib.sha256(content).hexdigest()
    return record


def verify_provenance(
    records: list[dict[str, Any]],
    store: EvidenceStore,
) -> list[str]:
    """Re-fetch every pinnable recorded reference and compare hashes.

    Returns the list of provenance failures (empty = verified). A mismatch is reported
    here, as a provenance failure — never folded into a scoring outcome. Unpinnable
    records carry no hash and are skipped by construction (there is nothing to verify).
    """
    failures: list[str] = []
    for record in records:
        if not record.get("pinnable"):
            continue
        source_id = str(record.get("source_id"))
        reference = record.get("reference")
        expected = record.get("content_sha256")
        try:
            content = store.fetch(source_id, reference if isinstance(reference, dict) else {})
        except Exception as exc:
            msg = f"{source_id}: re-fetch failed: {exc}"
            logger.warning("Provenance verification re-fetch error: %s", msg)
            failures.append(msg)
            continue
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            msg = f"{source_id}: content drifted (recorded {expected}, re-fetched {actual})"
            logger.warning("Provenance drift detected: %s", msg)
            failures.append(msg)
    return failures


@TARGETS.register("provenance_recorder", aliases=("provenance-recorder",))
class ProvenanceRecorderTarget(TargetRunner):
    """Compose an inner target with retrieval-evidence recording.

    Reads the item's declared ``evidence_sources`` (each ``{source_type, source_id,
    reference}``), fetches each from the evidence store, records one evidence record per
    source, runs the inner target, and attaches the records to the output's metadata.

    Two construction paths, one contract:

    * **DI** (tests, in-process composition): pass ``inner`` and ``store`` objects.
    * **Config** (registry-driven): pass ``inner_spec`` (a ``{type, params}`` mapping
      resolved through the TARGETS registry) plus either ``store_contents`` (an inline
      source_id → content mapping) or ``store_path`` (a JSON file of the same shape,
      read under ``DATA_ROOT`` confinement — how the shipped corpus supplies its 50
      evidence sources without restating them in YAML). No config string names an
      importable callable, so the wrapper adds no allowlist surface (ADR 0039).
    """

    def __init__(
        self,
        inner: TargetRunner | None = None,
        store: EvidenceStore | None = None,
        inner_spec: dict[str, Any] | None = None,
        store_contents: dict[str, str] | None = None,
        store_path: str | Path | None = None,
        clock: RetrievalClock | None = None,
    ) -> None:
        if inner is None:
            if not isinstance(inner_spec, dict) or "type" not in inner_spec:
                raise ValueError("provenance_recorder requires an inner target (inner= or inner_spec=)")
            inner = TARGETS.create(str(inner_spec["type"]), inner_spec.get("params") or {})
        if store is None:
            if store_path is not None and store_contents:
                raise ValueError("provenance_recorder takes store_path or store_contents, not both")
            store = (
                load_store_file(store_path)
                if store_path is not None
                else MappingEvidenceStore(
                    contents={str(k): v.encode("utf-8") for k, v in (store_contents or {}).items()}
                )
            )
        self.inner = inner
        self.store = store
        # The retrieval timestamp is genuinely wall-clock for live fetches; inject a
        # fixed clock for deterministic offline runs (the DI seam for "now", mirroring
        # agent_core.protocols.Clock without a new component edge).
        self._clock = clock

    def is_deterministic(self) -> bool | None:
        if self._clock is None:
            return None  # live clock: undeclared, the engine observes actual outputs
        inner_decl = getattr(self.inner, "is_deterministic", None)
        return inner_decl() if callable(inner_decl) else None

    def _retrieved_at(self) -> str:
        if self._clock is not None:
            return str(self._clock())
        return datetime.now(UTC).isoformat()

    def run(self, item: EvalItem) -> TargetOutput:
        sources = item.inputs.get("evidence_sources") if isinstance(item.inputs, dict) else None
        records: list[dict[str, Any]] = []
        if sources:
            retrieved_at = self._retrieved_at()
            for source in sources:
                if not isinstance(source, dict):
                    continue
                ref_raw = source.get("reference")
                reference: dict[str, Any] = dict(ref_raw) if isinstance(ref_raw, dict) else {}
                try:
                    content = self.store.fetch(str(source.get("source_id")), reference)
                except Exception as exc:
                    logger.debug("Failed fetching source %s: %s", source.get("source_id"), exc)
                    raise
                records.append(
                    build_evidence_record(
                        str(source.get("source_type", "")),
                        str(source.get("source_id")),
                        reference,
                        content,
                        retrieved_at=retrieved_at,
                    )
                )
        out = self.inner.run(item)
        metadata = dict(out.metadata or {})
        metadata[REQUIREMENTS_EVIDENCE_KEY] = records
        return TargetOutput(
            output=out.output,
            latency_ms=out.latency_ms,
            error=out.error,
            metadata=metadata,
            trajectory=out.trajectory,
        )
