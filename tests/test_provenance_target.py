#!/usr/bin/env python3
"""Tests for the provenance-recording target wrapper (requirements task 1).

Pins the spec's evidence-record contract: revision-scoped references carry a hash over
the bytes they returned, unpinnable sources carry NO content_sha256 key at all, and the
verification pass reports drift as a provenance failure distinct from scoring.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest

from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem, TargetOutput
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets.provenance import (
    EvidenceStore,
    MappingEvidenceStore,
    ProvenanceRecorderTarget,
    build_evidence_record,
    load_store_file,
    verify_provenance,
)

bootstrap()

REF = {"kind": "revision_export_link", "revision_id": "rev-9", "mime": "text/plain"}
UNPINNABLE_REF = {"kind": "context7_blob", "library": "/org/project", "query": "auth"}


def _item(sources: list[Any] | None) -> EvalItem:
    # `list[Any]`, not `list[dict]`: a dataset row is untrusted input, and some tests
    # here deliberately supply a malformed entry to prove the wrapper skips it.
    inputs: dict[str, Any] = {"question": "q"}
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
    """The config path must actually retrieve, not merely construct."""
    target = ProvenanceRecorderTarget(
        inner_spec={"type": "echo"},
        store_contents={"doc-1": "content"},
    )
    out = target.run(_item([{"source_type": "drive_doc", "source_id": "doc-1", "reference": REF}]))
    records = out.metadata[REQUIREMENTS_EVIDENCE_KEY]
    assert records[0]["content_sha256"] == hashlib.sha256(b"content").hexdigest()


def test_construction_without_any_inner_is_refused() -> None:
    with pytest.raises(ValueError, match="inner target"):
        ProvenanceRecorderTarget(inner=None, inner_spec=None)


def test_an_inner_spec_without_a_type_is_refused() -> None:
    with pytest.raises(ValueError, match="inner target"):
        ProvenanceRecorderTarget(inner_spec={"params": {}})


def test_a_non_mapping_source_entry_is_skipped_not_fetched() -> None:
    """A malformed dataset row must not take the run down, and must not be recorded."""
    store = MappingEvidenceStore(contents={"doc-1": b"bytes"})
    sources = ["not-a-mapping", {"source_type": "drive_doc", "source_id": "doc-1", "reference": REF}]
    out = _target(store).run(_item(sources))
    records = out.metadata[REQUIREMENTS_EVIDENCE_KEY]
    assert [r["source_id"] for r in records] == ["doc-1"]


def test_a_non_mapping_reference_records_an_unpinnable_source() -> None:
    store = MappingEvidenceStore(contents={"doc-1": b"bytes"})
    out = _target(store).run(_item([{"source_type": "drive_doc", "source_id": "doc-1", "reference": "rev-9"}]))
    record = out.metadata[REQUIREMENTS_EVIDENCE_KEY][0]
    assert record["pinnable"] is False
    assert "content_sha256" not in record


def test_items_whose_inputs_are_not_a_mapping_record_nothing() -> None:
    item = EvalItem(id="req-1", inputs=cast("dict[str, Any]", ["evidence_sources"]))
    assert _target(MappingEvidenceStore()).run(item).metadata[REQUIREMENTS_EVIDENCE_KEY] == []


class TestStoreFile:
    """``store_path`` is a config-driven filesystem read, so it obeys DATA_ROOT."""

    def _store(self, tmp_path: Path) -> Path:
        path = tmp_path / "store.json"
        path.write_text(json.dumps({"doc-1": "content"}), encoding="utf-8")
        return path

    def test_a_store_file_backs_retrieval(self, tmp_path: Path) -> None:
        target = ProvenanceRecorderTarget(inner=_EchoInner(), store_path=self._store(tmp_path))
        record = target.run(_item([{"source_type": "d", "source_id": "doc-1", "reference": REF}])).metadata[
            REQUIREMENTS_EVIDENCE_KEY
        ][0]
        assert record["content_sha256"] == hashlib.sha256(b"content").hexdigest()

    def test_a_store_outside_data_root_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An evidence store must not be the one config-named read that escapes confinement."""
        outside = self._store(tmp_path)
        confined = tmp_path / "allowed"
        confined.mkdir()
        monkeypatch.setenv("DATA_ROOT", str(confined))
        with pytest.raises(ValueError, match="outside DATA_ROOT"):
            load_store_file(outside)

    def test_a_traversal_segment_is_refused_before_resolution(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="traversal"):
            load_store_file(tmp_path / ".." / "store.json")

    def test_a_missing_store_names_the_path_rather_than_raising_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            load_store_file(tmp_path / "absent.json")

    def test_a_store_that_is_not_a_json_object_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "store.json"
        path.write_text(json.dumps(["doc-1"]), encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            load_store_file(path)

    def test_supplying_both_store_forms_is_refused_rather_than_silently_ranked(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not both"):
            ProvenanceRecorderTarget(
                inner=_EchoInner(), store_path=self._store(tmp_path), store_contents={"doc-1": "other"}
            )

    def test_an_explicit_store_object_still_wins_over_config_params(self, tmp_path: Path) -> None:
        """DI is the inner seam; naming a file must not override an injected store."""
        target = ProvenanceRecorderTarget(
            inner=_EchoInner(),
            store=MappingEvidenceStore(contents={"doc-1": b"injected"}),
            store_path=self._store(tmp_path),
        )
        record = target.run(_item([{"source_type": "d", "source_id": "doc-1", "reference": REF}])).metadata[
            REQUIREMENTS_EVIDENCE_KEY
        ][0]
        assert record["content_sha256"] == hashlib.sha256(b"injected").hexdigest()


def test_the_in_memory_store_satisfies_the_protocol_structurally() -> None:
    """The seam is structural: a live adapter needs the shape, not the base class."""
    assert isinstance(MappingEvidenceStore(), EvidenceStore)
    assert not isinstance(object(), EvidenceStore)


class TestDeterminismDeclaration:
    """``is_deterministic`` must not claim more than the wrapper can know."""

    def test_a_live_clock_makes_the_wrapper_undeclared(self) -> None:
        """The retrieval timestamp is wall-clock, so the wrapper cannot promise determinism."""
        assert _target(MappingEvidenceStore()).is_deterministic() is None

    def test_a_fixed_clock_defers_to_the_inner_target(self) -> None:
        target = ProvenanceRecorderTarget(inner=_EchoInner(), store=MappingEvidenceStore(), clock=lambda: "t0")
        assert target.is_deterministic() is True

    def test_an_inner_that_declares_nothing_leaves_the_wrapper_undeclared(self) -> None:
        class _Silent:
            def run(self, item: EvalItem) -> TargetOutput:
                return TargetOutput(output={})

        target = ProvenanceRecorderTarget(
            inner=cast("Any", _Silent()), store=MappingEvidenceStore(), clock=lambda: "t0"
        )
        assert target.is_deterministic() is None

    def test_a_fixed_clock_stamps_every_record_identically(self) -> None:
        store = MappingEvidenceStore(contents={"doc-1": b"a", "doc-2": b"b"})
        target = ProvenanceRecorderTarget(inner=_EchoInner(), store=store, clock=lambda: "2026-01-01T00:00:00+00:00")
        sources = [
            {"source_type": "drive_doc", "source_id": "doc-1", "reference": REF},
            {"source_type": "drive_doc", "source_id": "doc-2", "reference": REF},
        ]
        records = target.run(_item(sources)).metadata[REQUIREMENTS_EVIDENCE_KEY]
        assert {r["retrieved_at"] for r in records} == {"2026-01-01T00:00:00+00:00"}

    def test_a_live_clock_stamps_an_iso_utc_timestamp(self) -> None:
        store = MappingEvidenceStore(contents={"doc-1": b"a"})
        record = (
            _target(store)
            .run(_item([{"source_type": "d", "source_id": "doc-1", "reference": REF}]))
            .metadata[REQUIREMENTS_EVIDENCE_KEY][0]
        )
        assert datetime.fromisoformat(record["retrieved_at"]).tzinfo is not None
