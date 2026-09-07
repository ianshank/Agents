#!/usr/bin/env python3
"""Matrix rows for rca_ac_at_k and rca_component_match (M1, M2, M3, M5, M6).

Prototype slice of ``add-rca-eval-matrix``: two ranking scorers x scorer floor = 10
cells. Abstention scorers and the max-|Z| target land in later tasks.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

RCA_RANKING_SCORERS = ("rca_ac_at_k", "rca_component_match")
RCA_ABSTENTION_SCORERS = ("rca_onset_within_tolerance", "rca_abstention_correctness", "rca_false_accusation_rate")

_SPACE = ["cand_0", "cand_1", "cand_2", "cand_3"]
_ITEM = EvalItem(id="rca-m", inputs={"solution_space": _SPACE}, expected=["cand_0"])
_CTX = RunContext(config=None)


def score(name: str, ranking: Any, params: dict[str, Any] | None = None, it: EvalItem | None = None) -> ScoreResult:
    return SCORERS.create(name, params or {}).score(it or _ITEM, TargetOutput(output=ranking), _CTX)


class TestRcaAcAtK:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("rca_ac_at_k",)

    def test_m1_correctness_oracle_top1_is_strict_one(self) -> None:
        result = score("rca_ac_at_k", ["cand_0", "cand_1", "cand_2"])
        assert result.value == 1.0 and result.passed is True
        assert result.metadata["strict_ac_at_k"]["1"] == 1.0
        assert result.metadata["partial_ac_at_k"]["1"] == 1.0

    def test_m1_correctness_third_place_splits_cutoffs(self) -> None:
        result = score("rca_ac_at_k", ["cand_1", "cand_2", "cand_0", "cand_3"])
        assert result.metadata["strict_ac_at_k"]["1"] == 0.0
        assert result.metadata["strict_ac_at_k"]["3"] == 1.0
        assert result.metadata["strict_ac_at_k"]["5"] == 1.0
        assert result.value == 0.0

    def test_m2_edge_unanswerable_is_not_applicable(self) -> None:
        it = EvalItem(id="u", inputs={"candidates": _SPACE}, expected=[])
        result = score("rca_ac_at_k", ["cand_0"], it=it)
        assert result.passed is None

    def test_m2_edge_empty_ks_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="at least one k"):
            SCORERS.create("rca_ac_at_k", {"ks": []})

    def test_m3_type_malformed_ranking_is_not_applicable(self) -> None:
        result = score("rca_ac_at_k", 42)
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        ranking = ["cand_2", "cand_0", "cand_1"]
        a = score("rca_ac_at_k", ranking)
        b = score("rca_ac_at_k", ranking)
        assert a.value == b.value
        assert a.metadata == b.metadata

    def test_m6_error_missing_candidates_not_applicable(self) -> None:
        it = EvalItem(id="x", inputs={}, expected=["cand_0"])
        result = score("rca_ac_at_k", ["cand_0"], it=it)
        assert result.passed is None
        assert "candidate" in (result.comment or "").lower()


class TestRcaComponentMatch:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("rca_component_match",)

    def test_m1_correctness_top1_match(self) -> None:
        result = score("rca_component_match", ["cand_0", "cand_1"])
        assert result.value == 1.0 and result.passed is True

    def test_m1_correctness_outside_set_is_labelled(self) -> None:
        result = score("rca_component_match", ["not-in-set"])
        assert result.passed is False
        assert result.metadata["outside_candidate_set"] is True
        assert result.metadata["disposition"] == "outside_candidate_set"

    def test_m2_edge_in_set_wrong_distinct_from_outside(self) -> None:
        result = score("rca_component_match", ["cand_1"])
        assert result.passed is False
        assert result.metadata["in_set_wrong"] is True
        assert result.metadata["outside_candidate_set"] is False

    def test_m3_type_mapping_ranking_accepted(self) -> None:
        result = score("rca_component_match", {"ranked": ["cand_0"]})
        assert result.passed is True

    def test_m5_determinism_two_calls_agree(self) -> None:
        a = score("rca_component_match", ["cand_3"])
        b = score("rca_component_match", ["cand_3"])
        assert a.metadata == b.metadata and a.value == b.value

    def test_m6_error_missing_candidates_not_applicable(self) -> None:
        it = EvalItem(id="x", inputs={}, expected=["cand_0"])
        result = score("rca_component_match", ["cand_0"], it=it)
        assert result.passed is None


class TestRcaOnsetWithinTolerance:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("rca_onset_within_tolerance",)

    def test_m1_correctness_within_tolerance(self) -> None:
        it = EvalItem(
            id="o",
            inputs={"candidates": _SPACE, "onset": "2026-03-04T11:42:00+08:00", "timezone": "UTC+08:00"},
            expected=["cand_0"],
        )
        out = {"ranked": ["cand_0"], "onset": "2026-03-04T11:50:00+08:00"}
        result = score("rca_onset_within_tolerance", out, it=it)
        assert result.value == 1.0 and result.passed is True

    def test_m2_edge_shifted_zone_is_outside_tolerance(self) -> None:
        it = EvalItem(
            id="o",
            inputs={"candidates": _SPACE, "onset": "2026-03-04T11:42:00+08:00", "timezone": "UTC+08:00"},
            expected=["cand_0"],
        )
        out = {"ranked": ["cand_0"], "onset": "2026-03-04T11:42:00+00:00"}  # same wall clock, wrong zone
        result = score("rca_onset_within_tolerance", out, it=it)
        assert result.passed is False

    def test_m3_type_offset_free_claim_is_refused(self) -> None:
        it = EvalItem(
            id="o",
            inputs={"candidates": _SPACE, "onset": "2026-03-04T11:42:00+08:00", "timezone": "UTC+08:00"},
            expected=["cand_0"],
        )
        result = score("rca_onset_within_tolerance", {"ranked": ["cand_0"], "onset": "2026-03-04T11:42:00"}, it=it)
        assert result.passed is False

    def test_m5_determinism_two_calls_agree(self) -> None:
        it = EvalItem(
            id="o",
            inputs={"candidates": _SPACE, "onset": "2026-03-04T11:42:00+08:00", "timezone": "UTC+08:00"},
            expected=["cand_0"],
        )
        out = {"ranked": ["cand_0"], "onset": "2026-03-04T11:50:00+08:00"}
        a = score("rca_onset_within_tolerance", out, it=it)
        b = score("rca_onset_within_tolerance", out, it=it)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_no_onset_is_not_applicable(self) -> None:
        it = EvalItem(id="o", inputs={"candidates": _SPACE}, expected=["cand_0"])
        result = score("rca_onset_within_tolerance", {"ranked": ["cand_0"]}, it=it)
        assert result.passed is None


class TestRcaAbstentionCorrectness:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("rca_abstention_correctness",)

    def test_m1_correctness_decline_on_unanswerable(self) -> None:
        it = EvalItem(id="a", inputs={"candidates": _SPACE}, expected=[])
        result = score("rca_abstention_correctness", {"abstain": True}, it=it)
        assert result.value == 1.0 and result.passed is True

    def test_m2_edge_decline_on_answerable_is_incorrect(self) -> None:
        result = score("rca_abstention_correctness", {"abstain": True})
        assert result.passed is False
        assert result.metadata["disposition"] == "missed_abstention"

    def test_m3_type_malformed_ranking_is_not_applicable(self) -> None:
        result = score("rca_abstention_correctness", 42)
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        it = EvalItem(id="a", inputs={"candidates": _SPACE}, expected=[])
        a = score("rca_abstention_correctness", {"abstain": True}, it=it)
        b = score("rca_abstention_correctness", {"abstain": True}, it=it)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_missing_candidates_not_applicable(self) -> None:
        it = EvalItem(id="x", inputs={}, expected=[])
        result = score("rca_abstention_correctness", {"abstain": True}, it=it)
        assert result.passed is None


class TestRcaFalseAccusationRate:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("rca_false_accusation_rate",)

    def test_m1_correctness_named_cause_on_unanswerable_counts(self) -> None:
        it = EvalItem(id="f", inputs={"candidates": _SPACE}, expected=[])
        result = score("rca_false_accusation_rate", {"ranked": ["cand_1"]}, it=it)
        assert result.value == 1.0 and result.passed is False

    def test_m2_edge_decline_on_unanswerable_is_clean(self) -> None:
        it = EvalItem(id="f", inputs={"candidates": _SPACE}, expected=[])
        result = score("rca_false_accusation_rate", {"abstain": True}, it=it)
        assert result.value == 0.0 and result.passed is True

    def test_m3_type_malformed_ranking_is_not_applicable(self) -> None:
        it = EvalItem(id="f", inputs={"candidates": _SPACE}, expected=[])
        result = score("rca_false_accusation_rate", 42, it=it)
        assert result.passed is None

    def test_m5_determinism_two_calls_agree(self) -> None:
        it = EvalItem(id="f", inputs={"candidates": _SPACE}, expected=[])
        a = score("rca_false_accusation_rate", {"ranked": ["cand_1"]}, it=it)
        b = score("rca_false_accusation_rate", {"ranked": ["cand_1"]}, it=it)
        assert a.value == b.value and a.metadata == b.metadata

    def test_m6_error_answerable_item_is_not_applicable(self) -> None:
        result = score("rca_false_accusation_rate", {"ranked": ["cand_1"]})
        assert result.passed is None


class TestRcaMaxZTarget:
    """Target-kind row for the max-|Z| baseline (floor M1, M2, M3, M6)."""

    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("rca_maxz",)

    def test_m1_correctness_ranks_the_spiking_candidate_first(self) -> None:
        from eval_harness.plugins import TARGETS

        telemetry = {
            "metrics": {
                "cand_0": {"latency_ms": {"pre": [100.0, 101.0, 99.0], "post": [400.0, 401.0, 399.0]}},
                "cand_1": {"latency_ms": {"pre": [100.0, 101.0, 99.0], "post": [100.0, 101.0, 99.0]}},
            },
            "events": [],
        }
        it = EvalItem(id="t", inputs={"candidates": ["cand_0", "cand_1"], "telemetry": telemetry})
        out = TARGETS.create("rca_maxz", {}).run(it)
        assert out.output["ranked"][0] == "cand_0"

    def test_m2_edge_flat_telemetry_abstains(self) -> None:
        from eval_harness.plugins import TARGETS

        telemetry = {
            "metrics": {
                "cand_0": {"latency_ms": {"pre": [100.0, 100.0], "post": [100.0, 100.0]}},
            },
            "events": [],
        }
        it = EvalItem(id="t", inputs={"candidates": ["cand_0"], "telemetry": telemetry})
        out = TARGETS.create("rca_maxz", {}).run(it)
        assert out.output == {"abstain": True}

    def test_m3_type_missing_telemetry_is_an_error_not_a_crash(self) -> None:
        from eval_harness.plugins import TARGETS

        out = TARGETS.create("rca_maxz", {}).run(EvalItem(id="t", inputs={"candidates": ["cand_0"]}))
        assert out.error is not None

    def test_m6_determinism_two_runs_identical(self) -> None:
        from eval_harness.plugins import TARGETS

        telemetry = {
            "metrics": {
                "cand_0": {"latency_ms": {"pre": [100.0, 101.0], "post": [300.0, 301.0]}},
                "cand_1": {"latency_ms": {"pre": [100.0, 101.0], "post": [100.0, 101.0]}},
            },
            "events": [],
        }
        it = EvalItem(id="t", inputs={"candidates": ["cand_0", "cand_1"], "telemetry": telemetry})
        target = TARGETS.create("rca_maxz", {})
        assert target.run(it).output == target.run(it).output
