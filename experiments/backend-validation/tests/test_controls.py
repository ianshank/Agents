"""Unit tests for negative-control evaluation and HALT semantics (spec R5)."""

from __future__ import annotations

import pytest

from backend_validation.controls import HaltRequiredError, evaluate_expected_fail, halt_if_passed
from backend_validation.observables import Observable, OpOutcome
from backend_validation.registry import Predicate


def _obs(status: str, **extra: object) -> Observable:
    return Observable(
        probe_id="control.synthetic.unreachable",
        cell_id="controls.synthetic",
        backend="langfuse",
        rep_index=0,
        ts_utc="t",
        outcome=OpOutcome(operation="probe_endpoint", status=status, latency_ms=1.0),
        extra=dict(extra),
    )


PREDICATES = [Predicate(operation="probe_endpoint", field="status", equals="ok")]


def test_control_failing_as_expected_is_confirmed_absent() -> None:
    outcome = evaluate_expected_fail("control.synthetic.unreachable", "langfuse", PREDICATES, [_obs("error")])
    assert outcome.confirmed_absent and not outcome.passed_unexpectedly
    halt_if_passed(outcome)  # no exception


def test_unexpected_pass_requires_halt() -> None:
    outcome = evaluate_expected_fail("control.synthetic.unreachable", "langfuse", PREDICATES, [_obs("ok")])
    assert outcome.passed_unexpectedly
    with pytest.raises(HaltRequiredError, match="unexpected control PASS") as excinfo:
        halt_if_passed(outcome)
    assert excinfo.value.probe_id == "control.synthetic.unreachable"
    assert excinfo.value.backend == "langfuse"


def test_partial_hold_is_not_an_unexpected_pass() -> None:
    predicates = [
        Predicate(operation="probe_endpoint", field="status", equals="ok"),
        Predicate(operation="probe_endpoint", field="never_set", equals=True),
    ]
    outcome = evaluate_expected_fail("p", "b", predicates, [_obs("ok")])
    assert not outcome.passed_unexpectedly  # ALL predicates must hold to count as a pass
    assert outcome.held_predicates == 1 and outcome.total_predicates == 2


def test_no_predicates_never_passes() -> None:
    outcome = evaluate_expected_fail("p", "b", [], [_obs("ok")])
    assert not outcome.passed_unexpectedly and outcome.total_predicates == 0
