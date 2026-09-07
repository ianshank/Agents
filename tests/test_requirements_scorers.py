#!/usr/bin/env python3
"""Behavioural tests for the requirements-generation scorers (tasks 3.1-3.6).

Covers the spec scenarios: recall is the covered fraction of the DECLARED gold set, an
unsupported constraint is flagged against the recorded evidence, contradictory sources
are reported not resolved, diversity carries its temperature, and an asserted link is
not a link.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem, RunContext, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

CTX = RunContext(config=None)

REGISTERED = ("req_ac_recall", "req_scope_hallucination", "req_traceability_closure", "req_semantic_diversity")

GOLD = [
    {"id": "ac-1", "text": "persists"},
    {"id": "ac-2", "text": "rejects invalid"},
    {"id": "ac-3", "text": "refuses unauth"},
]


def item(*, gold: Any = ..., declared_tests: Any = ..., contradictions: Any = None) -> EvalItem:
    inputs: dict[str, Any] = {"epic": "epic text"}
    if declared_tests is not ...:
        inputs["declared_tests"] = declared_tests
    if contradictions is not None:
        inputs["contradictions"] = contradictions
    metadata: dict[str, Any] = {}
    if gold is not ...:
        metadata["gold_ac"] = gold
    return EvalItem(id="req-x", inputs=inputs, expected=None, metadata=metadata)


def output(
    reqs: list[dict[str, Any]] | None, *, temperature: Any = 0.7, recorded: list[str] | None = None
) -> TargetOutput:
    body: dict[str, Any] = {}
    if reqs is not None:
        body["requirements"] = reqs
    if temperature is not None:
        body["generation_temperature"] = temperature
    metadata: dict[str, Any] = {}
    if recorded is not None:
        metadata[REQUIREMENTS_EVIDENCE_KEY] = [{"source_id": s, "pinnable": True} for s in recorded]
    return TargetOutput(output=body, metadata=metadata)


def score(name: str, out: TargetOutput, it: EvalItem, params: dict[str, Any] | None = None):
    return SCORERS.create(name, params or {}).score(it, out, CTX)


@pytest.mark.parametrize("name", REGISTERED)
def test_registered_with_hyphenated_alias(name: str) -> None:
    assert name in SCORERS
    assert SCORERS.resolve(name.replace("_", "-")) == name


class TestAcRecall:
    def test_recall_is_the_covered_fraction_of_the_declared_set(self) -> None:
        """Spec: eight declared, six covered -> 0.75."""
        gold = [{"id": f"ac-{i}", "text": "t"} for i in range(8)]
        reqs = [{"id": "r1", "text": "a", "covers": [f"ac-{i}" for i in range(6)]}]
        result = score("req_ac_recall", output(reqs), item(gold=gold))
        assert result.value == 0.75
        assert result.metadata["missing"] == ["ac-6", "ac-7"]

    def test_no_gold_set_is_not_applicable(self) -> None:
        result = score("req_ac_recall", output([{"id": "r1", "covers": []}]), item(gold=None))
        assert result.passed is None
        empty_gold = score("req_ac_recall", output([{"id": "r1", "covers": []}]), item(gold=[]))
        assert empty_gold.passed is None
        no_reqs = score("req_ac_recall", TargetOutput(output=None), item(gold=GOLD))
        assert no_reqs.passed is None

    def test_full_coverage(self) -> None:
        reqs = [{"id": "r1", "covers": ["ac-1", "ac-2"]}, {"id": "r2", "covers": ["ac-3"]}]
        result = score("req_ac_recall", output(reqs), item(gold=GOLD))
        assert result.value == 1.0 and result.passed is True


class TestScopeHallucination:
    def test_an_unsupported_constraint_is_flagged(self) -> None:
        """Spec: evidence mentions no performance target; the set asserts a latency budget."""
        reqs = [{"id": "r1", "text": "latency under 100ms", "evidence_links": ["src-unrecorded"]}]
        result = score("req_scope_hallucination", output(reqs, recorded=["src-a"]), item(gold=GOLD))
        assert result.value == 1.0 and result.passed is False
        assert result.metadata["unsupported"] == ["r1"]

    def test_a_supported_requirement_is_not_flagged(self) -> None:
        reqs = [{"id": "r1", "text": "persists submissions", "evidence_links": ["src-a"]}]
        result = score("req_scope_hallucination", output(reqs, recorded=["src-a"]), item(gold=GOLD))
        assert result.value == 0.0 and result.passed is True

    def test_contradictory_sources_are_reported_not_resolved(self) -> None:
        reqs = [{"id": "r1", "text": "allows anonymous", "evidence_links": ["src-a"]}]
        it = item(gold=GOLD, contradictions=[["src-a", "src-b"]])
        result = score("req_scope_hallucination", output(reqs, recorded=["src-a", "src-b"]), it)
        assert result.passed is True  # supported, but NOT cleanly
        assert result.metadata["contradiction_citations"] == ["r1"]

    def test_absent_requirements_are_not_applicable(self) -> None:
        result = score("req_scope_hallucination", TargetOutput(output=None), item(gold=GOLD))
        assert result.passed is None
        empty = score("req_scope_hallucination", TargetOutput(output={"requirements": []}), item(gold=GOLD))
        assert empty.passed is None
        assert "empty" in (empty.comment or "")

    def test_malformed_requirements_are_not_applicable(self) -> None:
        malformed = score(
            "req_scope_hallucination", TargetOutput(output={"requirements": "not-a-list"}), item(gold=GOLD)
        )
        assert malformed.passed is None


class TestTraceabilityClosure:
    def test_a_missing_test_link_breaks_the_chain(self) -> None:
        reqs = [{"id": "r1", "covers": ["ac-1"], "test_links": []}]
        result = score("req_traceability_closure", output(reqs), item(gold=GOLD, declared_tests=["test_persists"]))
        assert result.value == 0.0 and result.passed is False
        assert result.metadata["incomplete"] == ["r1"]

    def test_an_asserted_link_is_not_a_link(self) -> None:
        """Prose claiming coverage by an undeclared test does not satisfy the chain."""
        reqs = [
            {"id": "r1", "covers": ["ac-1"], "test_links": ["test_not_declared"], "text": "covered by test_persists"}
        ]
        result = score("req_traceability_closure", output(reqs), item(gold=GOLD, declared_tests=["test_persists"]))
        assert result.passed is False

    def test_absent_requirements_are_not_applicable(self) -> None:
        result = score("req_traceability_closure", TargetOutput(output=None), item(gold=GOLD))
        assert result.passed is None
        empty = score("req_traceability_closure", TargetOutput(output={"requirements": []}), item(gold=GOLD))
        assert empty.passed is None

    def test_a_complete_chain_closes(self) -> None:
        reqs = [{"id": "r1", "covers": ["ac-1"], "test_links": ["test_persists"]}]
        result = score("req_traceability_closure", output(reqs), item(gold=GOLD, declared_tests=["test_persists"]))
        assert result.value == 1.0 and result.passed is True

    def test_a_corpus_without_tests_needs_only_the_ac_link(self) -> None:
        reqs = [{"id": "r1", "covers": ["ac-1"]}]
        result = score("req_traceability_closure", output(reqs), item(gold=GOLD, declared_tests=None))
        assert result.value == 1.0 and result.passed is True


class TestSemanticDiversity:
    def test_absent_requirements_are_not_applicable(self) -> None:
        result = score("req_semantic_diversity", TargetOutput(output=None), item(gold=GOLD))
        assert result.passed is None
        empty = score("req_semantic_diversity", TargetOutput(output={"requirements": []}), item(gold=GOLD))
        assert empty.passed is None
        single = score(
            "req_semantic_diversity", TargetOutput(output={"requirements": [{"text": "solo"}]}), item(gold=GOLD)
        )
        assert single.passed is None

    def test_a_score_without_a_temperature_is_uninterpretable(self) -> None:
        reqs = [{"text": "alpha beta"}, {"text": "gamma delta"}]
        result = score("req_semantic_diversity", output(reqs, temperature=None), item(gold=GOLD))
        assert result.passed is None
        assert "temperature" in (result.comment or "")

    def test_the_score_carries_its_temperature(self) -> None:
        reqs = [{"text": "alpha beta"}, {"text": "gamma delta"}]
        result = score("req_semantic_diversity", output(reqs, temperature=0.9), item(gold=GOLD))
        assert result.metadata["generation_temperature"] == 0.9

    def test_identical_members_score_below_varied_ones(self) -> None:
        collapsed = [{"text": "same words here"}, {"text": "same words here"}, {"text": "same words here"}]
        varied = [{"text": "alpha beta"}, {"text": "gamma delta"}, {"text": "epsilon zeta"}]
        low = score("req_semantic_diversity", output(collapsed), item(gold=GOLD))
        high = score("req_semantic_diversity", output(varied), item(gold=GOLD))
        assert low.value < high.value
        assert high.metadata["measured"].startswith("within-set")

    def test_the_floor_is_configured_not_literal(self) -> None:
        # A mid-diversity pair (shared tokens, distinct content) sits between the floors.
        reqs = [{"text": "the system persists data"}, {"text": "the system rejects input"}]
        strict = score("req_semantic_diversity", output(reqs), item(gold=GOLD), {"floor": 0.99})
        lax = score("req_semantic_diversity", output(reqs), item(gold=GOLD), {"floor": 0.01})
        assert strict.passed is False and lax.passed is True
        with pytest.raises(ValueError, match="floor"):
            SCORERS.create("req_semantic_diversity", {"floor": 0})
