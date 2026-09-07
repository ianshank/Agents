#!/usr/bin/env python3
"""Tests for the provenance-recording target wrapper (requirements task 1).

Pins the spec's evidence-record contract: revision-scoped references carry a hash over
the bytes they returned, unpinnable sources carry NO content_sha256 key at all, and the
verification pass reports drift as a provenance failure distinct from scoring.
"""

from __future__ import annotations

import pytest

from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem, TargetOutput
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets.provenance import (
    MappingEvidenceStore,
    ProvenanceRecorderTarget,
    build_evidence_record,
    verify_provenance,
)

bootstrap()

REF = {"kind": "revision_export_link", "revision_id": "rev-9", "mime": "text/plain"}
UNPINNABLE_REF = {"kind": "context7_blob", "library": "/org/project", "query": "auth"}


def _item(sources: list[dict] | None) -> EvalItem:
    inputs: dict = {"question": "q"}
    if sources is not None:
        inputs["evidence_sources"] = sources
    return EvalItem(id="req-1", inputs=inputs)


class _EchoInner:
    def run(self, item: EvalItem) -> TargetOutput:
        return TargetOutput(output={"text": "generated"}, metadata={"inner": True})

    def is_deterministic(self) -> bool:
        return True


def _target(store: MappingEvidenceStore) -> ProvenanceRecorderTarget:
    return ProvenanceRecorderTarget(inner=_EchoInner(), store=store)


def test_registered_with_hyphenated_alias() -> None:
    assert "provenance_recorder" in TARGETS
    assert TARGETS.resolve("provenance-recorder") == "provenance_recorder"


def test_pinnable_record_carries_a_hash_over_the_reference_bytes() -> None:
    record = build_evidence_record("drive_doc", "doc-1", REF, b"content", retrieved_at="2026-09-06T00:00:00+00:00")
    assert record["pinnable"] is True
    assert record["content_sha256"]


def test_an_unpinnable_record_carries_no_hash_key_at_all() -> None:
    """Spec 1.5: a reader must not be able to mistake a churn-prone hash for a verified one."""
    record = build_evidence_record(
        "context7", "lib-1", UNPINNABLE_REF, b"blob", retrieved_at="2026-09-06T00:00:00+00:00"
    )
    assert record["pinnable"] is False
    assert "content_sha256" not in record
    assert record["retrieved_at"]


def test_the_wrapper_records_evidence_and_preserves_the_inner_output() -> None:
    store = MappingEvidenceStore(contents={"doc-1": b"revision-bytes"})
    item = _item([{"source_type": "drive_doc", "source_id": "doc-1", "reference": REF}])
    out = _target(store).run(item)
    assert out.output == {"text": "generated"}
    assert out.metadata["inner"] is True  # inner metadata survives the wrap
    records = out.metadata[REQUIREMENTS_EVIDENCE_KEY]
    assert len(records) == 1
    assert records[0]["source_id"] == "doc-1"
    assert records[0]["pinnable"] is True


def test_an_item_with_no_sources_records_an_empty_evidence_list() -> None:
    out = _target(MappingEvidenceStore()).run(_item(None))
    assert out.metadata[REQUIREMENTS_EVIDENCE_KEY] == []


def test_verification_passes_on_stable_content() -> None:
    store = MappingEvidenceStore(contents={"doc-1": b"bytes"})
    record = build_evidence_record("drive_doc", "doc-1", REF, b"bytes", retrieved_at="t")
    assert verify_provenance([record], store) == []


def test_verification_detects_drift_as_a_provenance_failure() -> None:
    """Spec: a mutated source is detected by the provenance check, not merely recorded."""
    record = build_evidence_record("drive_doc", "doc-1", REF, b"original", retrieved_at="t")
    mutated = MappingEvidenceStore(contents={"doc-1": b"mutated"})
    failures = verify_provenance([record], mutated)
    assert len(failures) == 1
    assert "drifted" in failures[0]


def test_verification_skips_unpinnable_records_by_construction() -> None:
    record = build_evidence_record("context7", "lib-1", UNPINNABLE_REF, b"blob", retrieved_at="t")
    assert verify_provenance([record], MappingEvidenceStore()) == []


def test_verification_reports_a_refetch_failure_as_a_provenance_failure() -> None:
    record = build_evidence_record("drive_doc", "gone", REF, b"bytes", retrieved_at="t")
    failures = verify_provenance([record], MappingEvidenceStore())
    assert len(failures) == 1
    assert "re-fetch failed" in failures[0]


def test_a_missing_source_fails_the_run_loudly() -> None:
    with pytest.raises(KeyError, match="not in the store"):
        _target(MappingEvidenceStore()).run(
            _item([{"source_type": "drive_doc", "source_id": "absent", "reference": REF}])
        )


def test_inner_spec_and_store_contents_config_construction() -> None:
    target = ProvenanceRecorderTarget(
        inner_spec={"type": "echo"},
        store_contents={"doc-1": "content"},
    )
    assert target is not None
    with pytest.raises(ValueError, match="inner target"):
        ProvenanceRecorderTarget(inner=None, inner_spec=None)
