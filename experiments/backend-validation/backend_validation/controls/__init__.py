"""Negative-control evaluation (spec R5): a probe layer that cannot fail is untrustworthy.

Expected-fail probes come in two forms: matrix "absent" cells probed as controls (the
platform SHOULD lack the capability) and synthetic unreachable-endpoint probes (the layer
itself must notice a dead target). A control "passes" when all of its expected observables
hold — which for an expected-fail probe means something is wrong: either the matrix is
wrong (a finding!) or the probe layer is broken. Both demand a human, so an unexpected
pass HALTs the run (exit 4); it is never auto-resolved.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend_validation.observables import Observable
from backend_validation.registry import Predicate
from backend_validation.repetition import evaluate_predicates, majorities


class HaltRequiredError(RuntimeError):
    """Raised when an expected-fail control passed; carries the evidence pointer."""

    def __init__(self, probe_id: str, backend: str, detail: str) -> None:
        super().__init__(f"unexpected control PASS: {probe_id} on {backend} — {detail}")
        self.probe_id = probe_id
        self.backend = backend
        self.detail = detail


@dataclass(frozen=True)
class ControlOutcome:
    """Evaluation of one expected-fail probe on one backend."""

    probe_id: str
    backend: str
    passed_unexpectedly: bool
    held_predicates: int
    total_predicates: int

    @property
    def confirmed_absent(self) -> bool:
        return not self.passed_unexpectedly


def evaluate_expected_fail(
    probe_id: str,
    backend: str,
    predicates: list[Predicate],
    observables: list[Observable],
) -> ControlOutcome:
    """A control passes unexpectedly iff EVERY expected observable holds (majority-wise)."""
    verdicts = evaluate_predicates(predicates, observables)
    held = majorities(verdicts)
    return ControlOutcome(
        probe_id=probe_id,
        backend=backend,
        passed_unexpectedly=bool(held) and all(held),
        held_predicates=sum(held),
        total_predicates=len(held),
    )


def halt_if_passed(outcome: ControlOutcome) -> None:
    if outcome.passed_unexpectedly:
        raise HaltRequiredError(
            outcome.probe_id,
            outcome.backend,
            f"all {outcome.total_predicates} expected observables held on an expected-fail probe",
        )
