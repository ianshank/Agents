#!/usr/bin/env python3
"""Matrix rows for the requirements scorers and the provenance-recorder target.

Scorer floor (M1, M2, M3, M5, M6) for req_ac_recall, req_scope_hallucination,
req_traceability_closure, req_semantic_diversity; target floor (M1, M2, M3, M6) for
provenance_recorder. Cells are not methods: one parametrized method covers a column
(`_matrix_coverage.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem, RunContext, ScoreResult, TargetOutput
from eval_harness.plugins import SCORERS, TARGETS, bootstrap
from eval_harness.targets.provenance import MappingEvidenceStore

bootstrap()

REQUIREMENTS_SCORERS = (
    "req_ac_recall",
    "req_scope_hallucination",
    "req_traceability_closure",
    "req_semantic_diversity",
)

_CTX = RunContext(config=None)
_GOLD = [{"id": "ac-1", "text": "persists"}, {"id": "ac-2", "text": "rejects"}]
_REF = {"kind": "revision_export_link", "revision_id": "rev-1", "mime": "text/plain"}


def _item() -> EvalItem:
    return EvalItem(
        id="req-m",
        inputs={
            "epic": "epic",
            "declared_tests": ["test_persists"],
            "evidence_sources": [{"source_type": "drive_doc", "source_id": "doc-1", "reference": _REF}],
        },
        metadata={"gold_ac": _GOLD},
    )


def _out(reqs: list[dict[str, Any]] | None, temperature: Any = 0.7) -> TargetOutput:
    body: dict[str, Any] = {"generation_temperature": temperature}
    if reqs is not None:
        body["requirements"] = reqs
    return TargetOutput(
        output=body,
        metadata={REQUIREMENTS_EVIDENCE_KEY: [{"source_id": "doc-1", "pinnable": True}]},
    )


def score(name: str, out: TargetOutput, params: dict[str, Any] | None = None) -> ScoreResult:
    return SCORERS.create(name, params or {}).score(_item(), out, _CTX)


class TestReqAcRecall:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("req_ac_recall",)

    def test_m1_correctness_covered_fraction(self) -> None:
        result = score("req_ac_recall", _out([{"id": "r1", "covers": ["ac-1", "ac-2"]}]))
        assert result.value == 1.0 and result.passed is True

    def test_m2_edge_no_gold_set_not_applicable(self) -> None:
        it = EvalItem(id="x", inputs={}, metadata={})
        result = SCORERS.create("req_ac_recall", {}).score(it, _out([{"id": "r1", "covers": []}]), _CTX)
        assert result.passed is None

    def test_m3_type_malformed_output_not_applicable(self) -> None:
        result = score("req_ac_recall", TargetOutput(output="not-a-mapping"))
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        out = _out([{"id": "r1", "covers": ["ac-1"]}])
        a = score("req_ac_recall", out)
        b = score("req_ac_recall", out)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_missing_requirements_not_applicable(self) -> None:
        result = score("req_ac_recall", TargetOutput(output=None))
        assert result.passed is None


class TestReqScopeHallucination:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("req_scope_hallucination",)

    def test_m1_correctness_unsupported_is_flagged(self) -> None:
        result = score("req_scope_hallucination", _out([{"id": "r1", "evidence_links": ["unrecorded"]}]))
        assert result.value == 1.0 and result.passed is False

    def test_m2_edge_supported_is_clean(self) -> None:
        result = score("req_scope_hallucination", _out([{"id": "r1", "evidence_links": ["doc-1"]}]))
        assert result.value == 0.0 and result.passed is True

    def test_m3_type_malformed_output_not_applicable(self) -> None:
        result = score("req_scope_hallucination", TargetOutput(output=42))
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        out = _out([{"id": "r1", "evidence_links": ["doc-1"]}])
        a = score("req_scope_hallucination", out)
        b = score("req_scope_hallucination", out)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_empty_set_not_applicable(self) -> None:
        result = score("req_scope_hallucination", _out([]))
        assert result.passed is None


class TestReqTraceabilityClosure:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("req_traceability_closure",)

    def test_m1_correctness_complete_chain(self) -> None:
        result = score(
            "req_traceability_closure", _out([{"id": "r1", "covers": ["ac-1"], "test_links": ["test_persists"]}])
        )
        assert result.value == 1.0 and result.passed is True

    def test_m2_edge_missing_link_breaks_chain(self) -> None:
        result = score("req_traceability_closure", _out([{"id": "r1", "covers": ["ac-1"]}]))
        assert result.passed is False

    def test_m3_type_malformed_output_not_applicable(self) -> None:
        result = score("req_traceability_closure", TargetOutput(output=[1, 2]))
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        out = _out([{"id": "r1", "covers": ["ac-1"], "test_links": ["test_persists"]}])
        a = score("req_traceability_closure", out)
        b = score("req_traceability_closure", out)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_undeclared_test_link_breaks_chain(self) -> None:
        result = score("req_traceability_closure", _out([{"id": "r1", "covers": ["ac-1"], "test_links": ["nope"]}]))
        assert result.passed is False


class TestReqSemanticDiversity:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("req_semantic_diversity",)

    def test_m1_correctness_varied_set_scores_high(self) -> None:
        out = _out([{"text": "alpha beta"}, {"text": "gamma delta"}])
        result = score("req_semantic_diversity", out)
        assert result.value > 0.9 and result.passed is True

    def test_m2_edge_collapsed_set_scores_low(self) -> None:
        out = _out([{"text": "same words"}, {"text": "same words"}, {"text": "same words"}])
        result = score("req_semantic_diversity", out)
        assert result.value < 0.35 and result.passed is False

    def test_m3_type_missing_temperature_uninterpretable(self) -> None:
        out = _out([{"text": "alpha beta"}, {"text": "gamma delta"}], temperature=None)
        result = score("req_semantic_diversity", out)
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        out = _out([{"text": "alpha beta"}, {"text": "gamma delta"}])
        a = score("req_semantic_diversity", out)
        b = score("req_semantic_diversity", out)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_single_member_set_not_applicable(self) -> None:
        result = score("req_semantic_diversity", _out([{"text": "alone"}]))
        assert result.passed is None


class TestProvenanceRecorderTarget:
    """Target-kind row for the provenance-recording wrapper (floor M1, M2, M3, M6)."""

    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("provenance_recorder",)

    def test_m1_correctness_records_evidence(self) -> None:
        # Config-driven construction: inner target by registry spec, store by contents.
        target = TARGETS.create(
            "provenance_recorder",
            {"inner_spec": {"type": "echo"}, "store_contents": {"doc-1": "bytes"}},
        )
        out = target.run(_item())
        assert out.metadata[REQUIREMENTS_EVIDENCE_KEY][0]["source_id"] == "doc-1"

    def test_m2_edge_no_sources_records_empty(self) -> None:
        from eval_harness.targets.provenance import ProvenanceRecorderTarget

        class _Inner:
            def run(self, item: EvalItem) -> TargetOutput:
                return TargetOutput(output={})

            def is_deterministic(self) -> bool:
                return True

        it = EvalItem(id="x", inputs={})
        out = ProvenanceRecorderTarget(inner=_Inner(), store=MappingEvidenceStore()).run(it)
        assert out.metadata[REQUIREMENTS_EVIDENCE_KEY] == []

    def test_m3_type_missing_source_fails_loudly(self) -> None:
        from eval_harness.targets.provenance import ProvenanceRecorderTarget

        class _Inner:
            def run(self, item: EvalItem) -> TargetOutput:
                return TargetOutput(output={})

            def is_deterministic(self) -> bool:
                return True

        with pytest.raises(KeyError, match="not in the store"):
            ProvenanceRecorderTarget(inner=_Inner(), store=MappingEvidenceStore()).run(_item())

    def test_m6_determinism_two_runs_identical_records(self) -> None:
        from eval_harness.targets.provenance import ProvenanceRecorderTarget

        class _Inner:
            def run(self, item: EvalItem) -> TargetOutput:
                return TargetOutput(output={"requirements": []})

            def is_deterministic(self) -> bool:
                return True

        store = MappingEvidenceStore(contents={"doc-1": b"bytes"})
        # A fixed clock makes the retrieval timestamp reproducible; with the default
        # (live) clock the wrapper honestly declines to declare determinism.
        target = ProvenanceRecorderTarget(inner=_Inner(), store=store, clock=lambda: "2026-09-06T00:00:00+00:00")
        a = target.run(_item()).metadata[REQUIREMENTS_EVIDENCE_KEY]
        b = target.run(_item()).metadata[REQUIREMENTS_EVIDENCE_KEY]
        assert a == b
        assert target.is_deterministic() is None or target.is_deterministic() is True
        live = ProvenanceRecorderTarget(inner=_Inner(), store=store)
        assert live.is_deterministic() is None
