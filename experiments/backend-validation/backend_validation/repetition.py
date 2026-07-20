"""Repetition policy: k=1 for deterministic probes, k=3 majority for judge-class probes.

Disagreement across repetitions is EVIDENCE (the cell is flaky) and is reported per-rep;
nothing here averages anything (spec R6 / scoring rule 3 — a test asserts the absence of
any mean field).
"""

from __future__ import annotations

from dataclasses import dataclass

from backend_validation.observables import Observable
from backend_validation.registry import Predicate, Repetition
from backend_validation.rubric import predicate_holds

_K_BY_REPETITION: dict[str, int] = {"deterministic": 1, "judge_k3": 3}


def k_for(repetition: Repetition) -> int:
    return _K_BY_REPETITION[repetition]


@dataclass(frozen=True)
class PredicateVerdict:
    """One expected observable evaluated across every repetition."""

    predicate: Predicate
    per_rep: tuple[bool, ...]
    majority: bool
    flaky: bool


def evaluate_predicates(
    predicates: list[Predicate],
    observables: list[Observable],
) -> list[PredicateVerdict]:
    """Evaluate each predicate per repetition, then take the strict majority.

    The repetition count comes from the evidence itself (distinct ``rep_index`` values),
    so a run that produced fewer reps than planned is judged on what actually happened.
    """
    rep_indexes = sorted({observable.rep_index for observable in observables})
    if not rep_indexes:
        rep_indexes = [0]
    by_rep = {index: [obs for obs in observables if obs.rep_index == index] for index in rep_indexes}
    verdicts: list[PredicateVerdict] = []
    for predicate in predicates:
        per_rep = tuple(predicate_holds(predicate, by_rep[index]) for index in rep_indexes)
        majority = sum(per_rep) >= (len(per_rep) // 2) + 1
        verdicts.append(
            PredicateVerdict(
                predicate=predicate,
                per_rep=per_rep,
                majority=majority,
                flaky=len(set(per_rep)) > 1,
            )
        )
    return verdicts


def any_flaky(verdicts: list[PredicateVerdict]) -> bool:
    return any(verdict.flaky for verdict in verdicts)


def majorities(verdicts: list[PredicateVerdict]) -> list[bool]:
    return [verdict.majority for verdict in verdicts]
