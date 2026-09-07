#!/usr/bin/env python3
"""Behavioural tests for the RCA abstention/onset scorers (tasks 4.4-4.6).

Covers the spec scenarios: timezone-shifted onsets score outside tolerance, correct
abstention on unanswerable items, penalised confident guesses, and non-free abstention
on answerable items.
"""

from __future__ import annotations

from typing import Any

import pytest

from eval_harness.core.types import EvalItem, RunContext, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

CTX = RunContext(config=None)

REGISTERED = ("rca_onset_within_tolerance", "rca_abstention_correctness", "rca_false_accusation_rate")

SPACE = ["svc-a", "svc-b", "db-01", "cache-2"]
ONSET = "2026-03-04T11:42:00+08:00"


def item(
    *,
    correct: list[str] | None,
    onset: str | None = ONSET,
    candidates: list[str] | None = None,
) -> EvalItem:
    inputs: dict[str, Any] = {"candidates": candidates or SPACE}
    if onset is not None:
        inputs["onset"] = onset
        inputs["timezone"] = "UTC+08:00"
    return EvalItem(id="rca-x", inputs=inputs, expected=correct)


def score(name: str, output: Any, it: EvalItem, params: dict[str, Any] | None = None):
    return SCORERS.create(name, params or {}).score(it, TargetOutput(output=output), CTX)


@pytest.mark.parametrize("name", REGISTERED)
def test_registered_with_hyphenated_alias(name: str) -> None:
    assert name in SCORERS
    assert SCORERS.resolve(name.replace("_", "-")) == name


class TestOnsetWithinTolerance:
    def test_within_tolerance_is_correct(self) -> None:
        it = item(correct=["db-01"])
        out = {"ranked": ["db-01"], "onset": "2026-03-04T11:50:00+08:00"}  # +8 min
        result = score("rca_onset_within_tolerance", out, it)
        assert result.passed is True
        assert result.metadata["delta_seconds"] == 480.0

    def test_a_timezone_shifted_wall_clock_match_is_wrong(self) -> None:
        """The spec's headline scenario: same wall-clock reading, different zone."""
        it = item(correct=["db-01"])
        # Same wall clock (11:42:00) but UTC, not UTC+08:00 — 8 hours off.
        out = {"ranked": ["db-01"], "onset": "2026-03-04T11:42:00+00:00"}
        result = score("rca_onset_within_tolerance", out, it)
        assert result.passed is False
        assert result.metadata["delta_seconds"] == 28800.0
        # Both instants are recorded normalised to UTC, so the shift is visible.
        assert result.metadata["claimed_onset_utc"].endswith("+00:00")
        assert result.metadata["confirmed_onset_utc"].endswith("+00:00")

    def test_a_claim_without_offset_is_refused_not_localised(self) -> None:
        it = item(correct=["db-01"])
        out = {"ranked": ["db-01"], "onset": "2026-03-04T11:42:00"}  # no offset
        result = score("rca_onset_within_tolerance", out, it)
        assert result.passed is False
        assert "no offset" in (result.comment or "")

    def test_unanswerable_item_is_not_applicable(self) -> None:
        it = item(correct=[])
        result = score("rca_onset_within_tolerance", {"abstain": True}, it)
        assert result.passed is None

    def test_a_ranking_only_answer_is_not_applicable(self) -> None:
        it = item(correct=["db-01"])
        result = score("rca_onset_within_tolerance", {"ranked": ["db-01"]}, it)
        assert result.passed is None
        assert "no onset" in (result.comment or "")

    def test_tolerance_is_configured_not_literal(self) -> None:
        it = item(correct=["db-01"])
        out = {"ranked": ["db-01"], "onset": "2026-03-04T12:42:00+08:00"}  # +60 min
        wide = score("rca_onset_within_tolerance", out, it, {"tolerance_seconds": 7200})
        narrow = score("rca_onset_within_tolerance", out, it, {"tolerance_seconds": 60})
        assert wide.passed is True and narrow.passed is False
        with pytest.raises(ValueError, match="tolerance_seconds"):
            SCORERS.create("rca_onset_within_tolerance", {"tolerance_seconds": 0})


class TestAbstentionCorrectness:
    def test_correct_abstention_on_unanswerable(self) -> None:
        it = item(correct=[])
        result = score("rca_abstention_correctness", {"abstain": True}, it)
        assert result.passed is True
        assert result.metadata["disposition"] == "correct_abstention"

    def test_confident_guess_on_unanswerable_is_incorrect(self) -> None:
        it = item(correct=[])
        result = score("rca_abstention_correctness", {"ranked": ["svc-a"]}, it)
        assert result.passed is False
        assert result.metadata["disposition"] == "false_answer"

    def test_abstaining_on_answerable_is_not_free(self) -> None:
        it = item(correct=["db-01"])
        result = score("rca_abstention_correctness", {"abstain": True}, it)
        assert result.passed is False
        assert result.metadata["disposition"] == "missed_abstention"

    def test_answering_an_answerable_item_is_correct(self) -> None:
        it = item(correct=["db-01"])
        result = score("rca_abstention_correctness", {"ranked": ["svc-a"]}, it)
        assert result.passed is True
        assert result.metadata["disposition"] == "answered_answerable"


class TestFalseAccusationRate:
    def test_naming_a_cause_on_unanswerable_counts(self) -> None:
        it = item(correct=[])
        result = score("rca_false_accusation_rate", {"ranked": ["svc-a"]}, it)
        assert result.value == 1.0 and result.passed is False
        assert result.metadata["named"] == ["svc-a"]

    def test_declining_on_unanswerable_is_clean(self) -> None:
        it = item(correct=[])
        result = score("rca_false_accusation_rate", {"abstain": True}, it)
        assert result.value == 0.0 and result.passed is True

    def test_answerable_items_are_not_accusation_opportunities(self) -> None:
        it = item(correct=["db-01"])
        result = score("rca_false_accusation_rate", {"ranked": ["svc-a"]}, it)
        assert result.passed is None  # excluded from the pass_rate aggregate
