#!/usr/bin/env python3
"""Matrix rows for the four test-generation scorers (M1, M2, M3, M5, M6).

Its own file rather than grown inside ``test_matrix_eval_tools.py``: the cell-map extractor
globs ``test_matrix_*.py``, so a per-feature file is a first-class citizen (precedent:
``test_matrix_state_scorers.py``, ``test_matrix_panel_judge.py``).

Every test here is **pure** — evidence payloads are built inline and handed straight to a
scorer. No subprocess, no corpus, no filesystem. That is the capability's whole shape
(``targets/testgen.py`` executes, these read), and it is what makes twenty matrix cells
cheap to fill honestly. The target's own execution behaviour is covered by
``tests/test_testgen_target.py``, which does spend subprocesses.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap
from eval_harness.scorers.test_generation import NO_EVIDENCE, NOT_EXECUTABLE
from eval_harness.targets.testgen import EVIDENCE_KEY

bootstrap()

#: The four registered names. A literal cross-checked against the live census by the matrix
#: guard, so a stale entry fails loudly rather than silently under-covering.
TESTGEN_SCORERS = (
    "test_executability",
    "testgen_mutation_score",
    "testgen_green_on_correct",
    "requirement_obligation_recall",
)

#: The three that depend on executability, so report not-applicable when the suite did not
#: collect. ``test_executability`` is excluded because it is the one that decides that.
TESTGEN_DEPENDENT_SCORERS = (
    "testgen_mutation_score",
    "testgen_green_on_correct",
    "requirement_obligation_recall",
)

_ITEM = EvalItem(id="tg1", inputs={}, expected=None)
_CTX = RunContext(config=None)


def evidence(**overrides: Any) -> dict[str, Any]:
    """A healthy payload: 4 tests collected, all mutants killed, all obligations covered."""
    payload: dict[str, Any] = {
        "collected": 4,
        "collection_error": None,
        "green_on_correct": {"ran": 4, "failed": 0},
        "mutants": {"generated": 8, "equivalent_excluded": 2, "covered": 8, "killed": 8},
        "obligations_covered": ["OB-1", "OB-2"],
        "obligations_declared": ["OB-1", "OB-2"],
        "timed_out": False,
    }
    payload.update(overrides)
    return payload


def score(name: str, payload: dict[str, Any] | None, params: dict[str, Any] | None = None) -> ScoreResult:
    metadata = {} if payload is None else {EVIDENCE_KEY: payload}
    return SCORERS.create(name, params or {}).score(_ITEM, TargetOutput(output=None, metadata=metadata), _CTX)


class TestTestExecutability:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("test_executability",)

    def test_m1_correctness_a_collecting_suite_passes(self) -> None:
        result = score("test_executability", evidence())
        assert result.value == 1.0 and result.passed is True

    def test_m1_correctness_a_collection_error_fails(self) -> None:
        result = score("test_executability", evidence(collected=0, collection_error="RuntimeError: boom"))
        assert result.value == 0.0 and result.passed is False
        assert result.comment is not None and "RuntimeError" in result.comment

    def test_m1_correctness_zero_collected_is_a_failure_not_a_pass(self) -> None:
        """The case most easily mistaken for success: nothing raised, no test failed."""
        result = score("test_executability", evidence(collected=0))
        assert result.value == 0.0 and result.passed is False
        assert result.comment == "suite collected zero tests"


class TestTestgenMutationScore:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("testgen_mutation_score",)

    def test_m1_correctness_both_denominators_are_emitted_and_named(self) -> None:
        """Neither figure may be reported alone, and each must name its denominator."""
        result = score(
            "testgen_mutation_score",
            evidence(mutants={"generated": 10, "equivalent_excluded": 2, "covered": 4, "killed": 4}),
        )
        assert result.value == pytest.approx(0.4), "the headline defaults to the raw denominator"
        assert result.metadata["raw"] == pytest.approx(0.4)
        assert result.metadata["normalized"] == pytest.approx(1.0)
        assert result.metadata["raw_denominator"] == "non_equivalent_generated"
        assert result.metadata["normalized_denominator"] == "non_equivalent_covered"
        assert result.metadata["raw_denominator_count"] == 10
        assert result.metadata["normalized_denominator_count"] == 4

    def test_m1_correctness_covers_little_but_kills_what_it_reaches(self) -> None:
        """The spec's named scenario: high normalized, low raw, neither shown alone."""
        result = score(
            "testgen_mutation_score",
            evidence(mutants={"generated": 20, "equivalent_excluded": 0, "covered": 2, "killed": 2}),
        )
        assert result.metadata["normalized"] == pytest.approx(1.0)
        assert result.metadata["raw"] == pytest.approx(0.1)
        assert result.comment is not None and "raw" in result.comment and "normalized" in result.comment

    def test_m1_correctness_equivalent_mutants_are_excluded_from_both(self) -> None:
        result = score(
            "testgen_mutation_score",
            evidence(mutants={"generated": 4, "equivalent_excluded": 6, "covered": 4, "killed": 4}),
        )
        assert result.value == pytest.approx(1.0), "6 equivalent mutants must not cap the score"
        assert result.metadata["equivalent_excluded"] == 6

    def test_m1_correctness_the_headline_denominator_is_selectable(self) -> None:
        payload = evidence(mutants={"generated": 10, "equivalent_excluded": 0, "covered": 4, "killed": 4})
        assert score("testgen_mutation_score", payload, {"denominator": "normalized"}).value == pytest.approx(1.0)
        assert score("testgen_mutation_score", payload, {"denominator": "raw"}).value == pytest.approx(0.4)


class TestTestgenGreenOnCorrect:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("testgen_green_on_correct",)

    def test_m1_correctness_a_clean_suite_reports_a_zero_rate(self) -> None:
        result = score("testgen_green_on_correct", evidence())
        assert result.value == 0.0 and result.passed is True

    def test_m1_correctness_a_false_alarm_is_a_nonzero_rate(self) -> None:
        result = score("testgen_green_on_correct", evidence(green_on_correct={"ran": 4, "failed": 1}))
        assert result.value == pytest.approx(0.25) and result.passed is False
        assert result.metadata["false_alarms"] == 1

    def test_m1_correctness_a_false_alarm_does_not_move_the_mutation_score(self) -> None:
        """The spec's separation requirement, asserted across the two scorers together."""
        clean = evidence()
        noisy = evidence(green_on_correct={"ran": 4, "failed": 1})
        assert score("testgen_green_on_correct", clean).value != score("testgen_green_on_correct", noisy).value
        assert score("testgen_mutation_score", clean).value == score("testgen_mutation_score", noisy).value


class TestRequirementObligationRecall:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("requirement_obligation_recall",)

    def test_m1_correctness_recall_is_the_covered_fraction_of_the_declared_set(self) -> None:
        """The spec's worked example: four declared, three covered, 0.75."""
        result = score(
            "requirement_obligation_recall",
            evidence(
                obligations_declared=["OB-1", "OB-2", "OB-3", "OB-4"],
                obligations_covered=["OB-1", "OB-2", "OB-3"],
            ),
        )
        assert result.value == pytest.approx(0.75)
        assert result.metadata["uncovered"] == ["OB-4"]

    def test_m1_correctness_coverage_is_not_inferred_from_the_suite(self) -> None:
        """An id the item never declared cannot raise recall above the declared set."""
        result = score(
            "requirement_obligation_recall",
            evidence(obligations_declared=["OB-1"], obligations_covered=["OB-1", "OB-INVENTED"]),
        )
        assert result.value == pytest.approx(1.0)
        assert result.metadata["obligations_covered"] == 1, "an undeclared id must not be counted"

    def test_m1_correctness_no_declared_obligations_is_not_applicable(self) -> None:
        result = score("requirement_obligation_recall", evidence(obligations_declared=[]))
        assert result.passed is None
        assert result.comment == "item declares no gold obligations"


class TestTestgenScorersShared:
    """Cross-scorer dimensions, parametrized over all four."""

    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = TESTGEN_SCORERS

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m2_edge_absent_evidence_is_not_applicable_not_a_zero(self, name: str) -> None:
        """A missing payload and a genuinely bad suite must stay distinguishable."""
        result = score(name, None)
        assert result.passed is None
        assert result.comment == NO_EVIDENCE

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m2_edge_a_wrongly_shaped_payload_degrades_rather_than_raising(self, name: str) -> None:
        result = SCORERS.create(name, {}).score(
            _ITEM, TargetOutput(output=None, metadata={EVIDENCE_KEY: "not a mapping"}), _CTX
        )
        assert result.passed is None and result.comment == NO_EVIDENCE

    @pytest.mark.parametrize("name", TESTGEN_DEPENDENT_SCORERS)
    def test_m2_edge_a_non_executable_suite_makes_the_others_not_applicable(self, name: str) -> None:
        """A mutation score over a suite that never ran is meaningless, not low."""
        result = score(name, evidence(collected=0, collection_error="SyntaxError"))
        assert result.passed is None and result.comment == NOT_EXECUTABLE

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m2_edge_the_on_missing_value_is_configurable(self, name: str) -> None:
        """The emitted value still enters the mean, so it is a knob and not a constant."""
        assert score(name, None, {"on_missing": 0.5}).value == pytest.approx(0.5)

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m3_type_safety(self, name: str) -> None:
        result = score(name, evidence())
        assert isinstance(result, ScoreResult)
        assert isinstance(result.value, float)
        assert isinstance(result.passed, bool)
        assert isinstance(result.metadata, dict)

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m5_determinism_same_payload_scores_identically(self, name: str) -> None:
        """The purity requirement: no clock, no random source, no environment."""
        payload = evidence(mutants={"generated": 7, "equivalent_excluded": 1, "covered": 5, "killed": 3})
        verdicts = {(r.value, r.passed, r.comment) for r in (score(name, payload) for _ in range(5))}
        assert len(verdicts) == 1

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m5_determinism_key_order_does_not_change_the_verdict(self, name: str) -> None:
        """Dict insertion order is the property that genuinely varies in-process."""
        forward = evidence()
        reversed_payload = {key: forward[key] for key in reversed(list(forward))}
        assert list(forward) != list(reversed_payload)
        first, second = score(name, forward), score(name, reversed_payload)
        assert (first.value, first.passed) == (second.value, second.passed)

    @pytest.mark.parametrize("name", TESTGEN_SCORERS)
    def test_m6_error_unknown_param_is_rejected_at_construction(self, name: str) -> None:
        with pytest.raises(TypeError):
            SCORERS.create(name, {"not_a_param": 1})

    def test_m6_error_an_unknown_denominator_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="denominator must be one of"):
            SCORERS.create("testgen_mutation_score", {"denominator": "made_up"})

    def test_m6_error_zero_non_equivalent_mutants_is_not_applicable(self) -> None:
        """An item that cannot discriminate must not be scored as a failing suite."""
        result = score(
            "testgen_mutation_score",
            evidence(mutants={"generated": 0, "equivalent_excluded": 5, "covered": 0, "killed": 0}),
        )
        assert result.passed is None
        assert result.comment == "no non-equivalent mutants for this item"

    def test_m6_error_a_zero_test_denominator_does_not_divide_by_zero(self) -> None:
        result = score("testgen_green_on_correct", evidence(green_on_correct={"ran": 0, "failed": 0}))
        assert result.value == 0.0
