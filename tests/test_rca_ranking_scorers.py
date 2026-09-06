#!/usr/bin/env python3
"""Behavioural tests for rca_ac_at_k and rca_component_match (tasks 1.1-1.2).

Prototyped against the sdlc ``solution_space`` / ``correct`` shape via the fixture
copy under ``tests/fixtures/rca/`` — never by importing ``flow-corpus/`` at runtime.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pytest

from eval_harness.core.types import EvalItem, RunContext, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

CTX = RunContext(config=None)
FIXTURE_RAW = Path(__file__).resolve().parent / "fixtures" / "rca" / "sdlc_shape.jsonl"
FIXTURE_ITEMS = Path(__file__).resolve().parent / "fixtures" / "rca" / "sdlc_eval_items.jsonl"

REGISTERED = ("rca_ac_at_k", "rca_component_match")


def item(
    *,
    solution_space: list[str] | None = None,
    candidates: list[str] | None = None,
    correct: list[str] | None = None,
    expected: Any = ...,
    item_id: str = "rca1",
) -> EvalItem:
    inputs: dict[str, Any] = {}
    if solution_space is not None:
        inputs["solution_space"] = solution_space
    if candidates is not None:
        inputs["candidates"] = candidates
    if correct is not None and expected is ...:
        # raw-shape fallback path
        inputs["correct"] = correct
        exp: Any = None
    elif expected is ...:
        exp = correct
    else:
        exp = expected
    return EvalItem(id=item_id, inputs=inputs, expected=exp)


def score(name: str, ranking: Any, it: EvalItem, params: dict[str, Any] | None = None):
    return SCORERS.create(name, params or {}).score(it, TargetOutput(output=ranking), CTX)


@pytest.mark.parametrize("name", REGISTERED)
def test_registered_with_hyphenated_alias(name: str) -> None:
    assert name in SCORERS
    assert SCORERS.resolve(name.replace("_", "-")) == name


@pytest.mark.parametrize("name", REGISTERED)
def test_default_score_name_matches_registration(name: str) -> None:
    assert SCORERS.create(name, {}).name == name


def test_missing_candidates_is_not_applicable() -> None:
    it = EvalItem(id="x", inputs={}, expected=["a"])
    for name in REGISTERED:
        result = score(name, ["a"], it)
        assert result.passed is None
        assert "candidate" in (result.comment or "").lower()


def test_unanswerable_item_makes_ac_at_k_not_applicable() -> None:
    it = item(candidates=["a", "b"], correct=[])
    result = score("rca_ac_at_k", ["a"], it)
    assert result.passed is None
    assert "not applicable" in (result.comment or "").lower() or "no confirmed" in (result.comment or "").lower()


def test_correct_cause_ranked_third() -> None:
    """Spec scenario: AC@1=0, AC@3=AC@5=1 when the gold is third."""
    space = ["a", "b", "c", "d", "e"]
    it = item(solution_space=space, correct=["c"])
    ranking = ["a", "b", "c", "d", "e"]
    result = score("rca_ac_at_k", ranking, it)
    assert result.metadata["strict_ac_at_k"]["1"] == 0.0
    assert result.metadata["strict_ac_at_k"]["3"] == 1.0
    assert result.metadata["strict_ac_at_k"]["5"] == 1.0
    assert result.value == 0.0  # primary_k defaults to 1 (strict)
    assert "strict" in (result.comment or "")
    assert "partial" in (result.comment or "")


def test_partial_credits_fraction_of_multiple_correct() -> None:
    it = item(candidates=["a", "b", "c", "d"], correct=["a", "c"])
    result = score("rca_ac_at_k", ["a", "b", "x"], it, params={"primary_k": 3, "ks": [1, 3, 5]})
    assert result.metadata["strict_ac_at_k"]["3"] == 1.0  # at least one hit
    assert result.metadata["partial_ac_at_k"]["3"] == pytest.approx(0.5)
    assert result.metadata["partial_ac_at_k"]["1"] == pytest.approx(0.5)


def test_component_match_distinguishes_outside_set() -> None:
    it = item(solution_space=["a", "b", "c"], correct=["a"])
    outside = score("rca_component_match", ["z", "a"], it)
    assert outside.passed is False
    assert outside.metadata["outside_candidate_set"] is True
    assert outside.metadata["disposition"] == "outside_candidate_set"

    wrong = score("rca_component_match", ["b"], it)
    assert wrong.passed is False
    assert wrong.metadata["outside_candidate_set"] is False
    assert wrong.metadata["in_set_wrong"] is True
    assert wrong.metadata["disposition"] == "in_set_wrong"

    hit = score("rca_component_match", ["a", "b"], it)
    assert hit.passed is True
    assert hit.value == 1.0


def test_solution_space_and_candidates_keys_both_work() -> None:
    a = item(solution_space=["x", "y"], correct=["x"])
    b = item(candidates=["x", "y"], correct=["x"])
    for name in REGISTERED:
        assert score(name, ["x"], a).passed is True
        assert score(name, ["x"], b).passed is True


def test_ranking_dict_shapes() -> None:
    it = item(candidates=["a", "b"], correct=["b"])
    assert score("rca_ac_at_k", {"ranked": ["b", "a"]}, it).value == 1.0
    assert score("rca_component_match", {"ranking": ["b"]}, it).passed is True


def _oracle_rank_correct_first(row: dict[str, Any]) -> list[str]:
    """Oracle: confirmed cause first, then the rest of the solution space."""
    space = list(row["solution_space"])
    correct = list(row["correct"])
    rest = [c for c in space if c not in correct]
    return correct + rest


def _load_raw_fixture() -> list[dict[str, Any]]:
    rows = []
    for line in FIXTURE_RAW.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def test_fixture_has_two_hundred_sdlc_shaped_rows() -> None:
    rows = _load_raw_fixture()
    assert len(rows) == 200
    assert FIXTURE_ITEMS.is_file()
    for row in rows:
        assert "solution_space" in row and "correct" in row
        assert len(row["solution_space"]) == 4
        assert len(row["correct"]) == 1


def test_oracle_on_sdlc_fixture_is_perfect_and_records_distribution() -> None:
    """Task 1.2: confirm scorers behave on 200 known rows; distribution → review.md note.

    Oracle ranking (correct first) must score AC@1=1 and component match=1 on every
    answerable row. A shuffled-last ranking must score AC@1=0.
    """
    rows = _load_raw_fixture()
    ac = SCORERS.create("rca_ac_at_k", {})
    cm = SCORERS.create("rca_component_match", {})

    ac_values: list[float] = []
    cm_values: list[float] = []
    ac_at_3_when_third: list[float] = []

    for row in rows:
        it = item(
            solution_space=row["solution_space"],
            correct=row["correct"],
            item_id=row["instance_id"],
        )
        oracle = _oracle_rank_correct_first(row)
        ac_hit = ac.score(it, TargetOutput(output=oracle), CTX)
        cm_hit = cm.score(it, TargetOutput(output=oracle), CTX)
        assert ac_hit.value == 1.0 and ac_hit.passed is True
        assert cm_hit.value == 1.0 and cm_hit.passed is True
        ac_values.append(ac_hit.value)
        cm_values.append(cm_hit.value)

        # Put gold third: AC@1=0, AC@3=1
        space = list(row["solution_space"])
        gold = row["correct"][0]
        others = [c for c in space if c != gold]
        third = [*others[:2], gold, *others[2:]]
        ac_third = ac.score(it, TargetOutput(output=third), CTX)
        assert ac_third.metadata["strict_ac_at_k"]["1"] == 0.0
        assert ac_third.metadata["strict_ac_at_k"]["3"] == 1.0
        ac_at_3_when_third.append(ac_third.metadata["strict_ac_at_k"]["3"])

        # Wrong top-1 inside the set
        wrong_top = [others[0], gold] if others else [gold]
        cm_miss = cm.score(it, TargetOutput(output=wrong_top), CTX)
        if others:
            assert cm_miss.value == 0.0
            assert cm_miss.metadata["in_set_wrong"] is True

    assert statistics.mean(ac_values) == 1.0
    assert statistics.mean(cm_values) == 1.0
    assert statistics.mean(ac_at_3_when_third) == 1.0
    # Observed distribution summary is asserted here; prose lands in review.md.
    assert len(ac_values) == 200
