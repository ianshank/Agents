#!/usr/bin/env python3
"""Matrix rows for rca_ac_at_k and rca_component_match (M1, M2, M3, M5, M6).

Prototype slice of ``add-rca-eval-matrix``: two ranking scorers × scorer floor = 10
cells. Abstention scorers and the max-|Z| target land in later tasks.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

RCA_RANKING_SCORERS = ("rca_ac_at_k", "rca_component_match")

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
