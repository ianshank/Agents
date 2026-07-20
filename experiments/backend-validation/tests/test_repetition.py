"""Unit tests for the k-repetition policy: majority, flakiness, no averaging anywhere."""

from __future__ import annotations

import dataclasses

from backend_validation.observables import Observable, OpOutcome
from backend_validation.registry import Predicate
from backend_validation.repetition import PredicateVerdict, any_flaky, evaluate_predicates, k_for, majorities


def _obs(rep_index: int, status: str) -> Observable:
    return Observable(
        probe_id="l1.x.y",
        cell_id="cell",
        backend="b",
        rep_index=rep_index,
        ts_utc="t",
        outcome=OpOutcome(operation="op", status=status, latency_ms=1.0),
    )


PRED = Predicate(operation="op", field="status", equals="ok")


def test_k_for_maps_repetition_classes() -> None:
    assert k_for("deterministic") == 1
    assert k_for("judge_k3") == 3


def test_unanimous_reps_are_clean_majority() -> None:
    verdicts = evaluate_predicates([PRED], [_obs(0, "ok"), _obs(1, "ok"), _obs(2, "ok")])
    assert majorities(verdicts) == [True]
    assert not any_flaky(verdicts)
    assert verdicts[0].per_rep == (True, True, True)


def test_two_of_three_majority_is_flagged_flaky_never_averaged() -> None:
    verdicts = evaluate_predicates([PRED], [_obs(0, "ok"), _obs(1, "error"), _obs(2, "ok")])
    verdict = verdicts[0]
    assert verdict.majority is True
    assert verdict.flaky is True
    assert verdict.per_rep == (True, False, True)  # per-rep outcomes preserved verbatim
    # No averaging anywhere: the verdict carries no mean/average/score field.
    field_names = {field.name for field in dataclasses.fields(PredicateVerdict)}
    assert field_names == {"predicate", "per_rep", "majority", "flaky"}


def test_one_of_three_fails_majority() -> None:
    verdicts = evaluate_predicates([PRED], [_obs(0, "ok"), _obs(1, "error"), _obs(2, "error")])
    assert verdicts[0].majority is False and verdicts[0].flaky is True


def test_single_rep_is_its_own_majority() -> None:
    verdicts = evaluate_predicates([PRED], [_obs(0, "error")])
    assert verdicts[0].majority is False and verdicts[0].flaky is False


def test_no_observables_evaluates_falsey_without_crashing() -> None:
    verdicts = evaluate_predicates([PRED], [])
    assert verdicts[0].majority is False and verdicts[0].per_rep == (False,)
