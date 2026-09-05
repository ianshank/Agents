#!/usr/bin/env python3
"""Validation script for F-065 - test-generation evaluation: execute, then read.

Implements ``openspec/changes/add-testgen-eval-matrix`` task 6.1. Every check below is
established by RUNNING the thing it describes — the F-063 lesson, where a validator that
inspected shapes and concluded a cell was falsifiable was itself the defect. A sandbox is
built, a suite is executed against a reference and a mutant, and the scorers are asked what
they make of the evidence.

Checks:
    1.  Executing model-authored code is gated: the suite-execution target is refused when
        it is outside the callable allowlist, and the refusal happens BEFORE any generated
        code runs (ADR 0039, deny-by-default).
    2.  The target really executes: a suite driving the input at which a mutant diverges
        kills it, and a suite driving an input where it agrees does not. Both established
        by running the sandbox, so "covered" is measured rather than asserted.
    3.  A suite red on correct code cannot claim the kill. Without this rule a false-alarm
        defect reads as perfect fault detection.
    4.  Absent evidence yields "not applicable", never a zero, for all four scorers. A
        missing payload and a total agent failure must stay distinguishable.
    5.  Both mutation denominators are emitted on every verdict, each labelled with the
        count it was computed from, and equivalent mutants are excluded from both.
    6.  The scorers are pure: scoring one payload twice yields identical verdicts, and no
        scorer opens a socket or starts a subprocess.
    7.  Every shipped gate rule for this capability is advisory, so no uncalibrated
        threshold blocks a run.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
from typing import Any
from unittest import mock

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

#: The four scorers this feature registers.
_SCORERS = (
    "test_executability",
    "testgen_mutation_score",
    "testgen_green_on_correct",
    "requirement_obligation_recall",
)

#: The config whose gate rules must all be advisory.
_CONFIG = os.path.join(PROJECT_ROOT, "config", "testgen_eval.yaml")

#: The dotted path a configuration names to reach the suite-execution target.
_TARGET_PATH = "eval_harness.targets.testgen:run_generated_suite"

#: A one-branch focal method and a mutant that differs only at ``n == 2``.
_FOCAL = "def add(n, k):\n    if n < 2:\n        return n + k\n    return k - n\n"
_MUTANT_SOURCE = "def add(n, k):\n    if n <= 2:\n        return n + k\n    return k - n\n"
_GRID = [[0, 0], [2, 1]]

_KILLING_SUITE = "from focal import add\n\ndef test_boundary():\n    assert add(2, 1) == -1\n"
_BLIND_SUITE = "from focal import add\n\ndef test_origin():\n    assert add(0, 0) == 0\n"
_RED_SUITE = "from focal import add\n\ndef test_wrong():\n    assert add(2, 1) == 999\n"


def _item(suite: str) -> dict[str, Any]:
    return {
        "focal_name": "add",
        "reference": _FOCAL,
        "suite": suite,
        "mutants": [
            {"id": "M1", "kind": "relational", "equivalent": False, "source": _MUTANT_SOURCE, "differs_at": [1]},
            {"id": "M2", "kind": "relational", "equivalent": True, "source": _FOCAL, "differs_at": []},
        ],
        "obligations": [{"id": "OB-1", "witness_mutant": "M1"}],
        "grid": _GRID,
    }


def _evidence(suite: str) -> dict[str, Any]:
    from eval_harness.targets.testgen import EVIDENCE_KEY, run_generated_suite

    result = run_generated_suite(_item(suite))
    payload = result.metadata.get(EVIDENCE_KEY)
    assert isinstance(payload, dict)
    return payload


def _score(name: str, payload: dict[str, Any] | None, params: dict[str, Any] | None = None) -> Any:
    from eval_harness.core.types import TESTGEN_EVIDENCE_KEY, EvalItem, RunContext, TargetOutput
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()
    metadata = {} if payload is None else {TESTGEN_EVIDENCE_KEY: payload}
    scorer = SCORERS.create(name, params or {})
    return scorer.score(
        EvalItem(id="v", inputs={}, expected=None),
        TargetOutput(output=None, metadata=metadata),
        RunContext(config=None),
    )


def _check_execution_is_gated(errors: list[str]) -> None:
    from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV, DisallowedImportError
    from eval_harness.core.types import EvalItem
    from eval_harness.plugins import TARGETS, bootstrap

    bootstrap()
    target = TARGETS.create("callable", {"path": _TARGET_PATH})
    saved = os.environ.get(CALLABLE_ALLOWLIST_ENV)
    os.environ[CALLABLE_ALLOWLIST_ENV] = "something_else"
    try:
        target.run(EvalItem(id="v", inputs=_item(_KILLING_SUITE), expected=None))
    except DisallowedImportError:
        refused = True
    except Exception:  # any other failure means the gate is not the thing that stopped it
        refused = False
    else:
        refused = False
    finally:
        if saved is None:
            os.environ.pop(CALLABLE_ALLOWLIST_ENV, None)
        else:
            os.environ[CALLABLE_ALLOWLIST_ENV] = saved

    _check(
        refused,
        "an unlisted suite-execution target is refused by the callable allowlist before any "
        "generated code runs (ADR 0039, deny-by-default)",
        errors,
    )


def _check_the_sandbox_really_executes(errors: list[str]) -> None:
    killing = _evidence(_KILLING_SUITE)
    blind = _evidence(_BLIND_SUITE)

    _check(
        killing["collected"] == 1 and killing["collection_error"] is None,
        f"a valid suite is collected and run (observed {killing['collected']} test(s))",
        errors,
    )
    _check(
        killing["mutants"]["killed"] == 1 and killing["mutants"]["covered"] == 1,
        f"a suite driving the diverging input covers AND kills the mutant (observed {killing['mutants']})",
        errors,
    )
    _check(
        blind["mutants"]["killed"] == 0 and blind["mutants"]["covered"] == 0,
        f"a suite driving only an agreeing input neither covers nor kills it, so 'covered' "
        f"is measured rather than assumed (observed {blind['mutants']})",
        errors,
    )
    _check(
        killing["obligations_covered"] == ["OB-1"] and blind["obligations_covered"] == [],
        "obligation coverage follows the witness mutant, never the suite's own claims",
        errors,
    )


def _check_a_red_suite_cannot_claim_the_kill(errors: list[str]) -> None:
    red = _evidence(_RED_SUITE)
    _check(
        red["green_on_correct"]["failed"] == 1 and red["mutants"]["killed"] == 0,
        "a test already failing on correct code kills nothing -- otherwise a false-alarm "
        f"defect reads as perfect fault detection (observed {red['green_on_correct']}, {red['mutants']})",
        errors,
    )


def _check_absent_evidence_is_not_a_zero(errors: list[str]) -> None:
    for name in _SCORERS:
        result = _score(name, None)
        _check(
            result.passed is None,
            f"{name} reports not-applicable rather than a failing score when evidence is absent",
            errors,
        )
    non_executable = _evidence(_KILLING_SUITE)
    non_executable["collected"] = 0
    non_executable["collection_error"] = "SyntaxError"
    for name in _SCORERS:
        if name == "test_executability":
            continue
        _check(
            _score(name, non_executable).passed is None,
            f"{name} is not-applicable for a suite that never collected -- a mutation score "
            "over a suite that never ran is meaningless, not low",
            errors,
        )


def _check_both_denominators_are_emitted(errors: list[str]) -> None:
    payload = _evidence(_BLIND_SUITE)
    payload["mutants"] = {"generated": 10, "equivalent_excluded": 3, "covered": 4, "killed": 4}
    result = _score("testgen_mutation_score", payload)
    metadata = result.metadata
    _check(
        metadata.get("raw") == 0.4 and metadata.get("normalized") == 1.0,
        f"raw and normalized figures are both emitted (observed raw={metadata.get('raw')}, "
        f"normalized={metadata.get('normalized')})",
        errors,
    )
    _check(
        metadata.get("raw_denominator") == "non_equivalent_generated"
        and metadata.get("normalized_denominator") == "non_equivalent_covered"
        and metadata.get("raw_denominator_count") == 10
        and metadata.get("normalized_denominator_count") == 4,
        "each figure names the denominator it used and the count it was computed from",
        errors,
    )
    _check(
        metadata.get("equivalent_excluded") == 3,
        "equivalent mutants are excluded from both denominators, and the count is recorded",
        errors,
    )


def _check_scorers_are_pure(errors: list[str]) -> None:
    payload = _evidence(_KILLING_SUITE)
    for name in _SCORERS:
        verdicts = {(_score(name, payload).value, _score(name, payload).passed) for _ in range(3)}
        _check(len(verdicts) == 1, f"{name} is deterministic over one payload", errors)

    with (
        mock.patch.object(socket.socket, "connect", side_effect=AssertionError("egress")) as connect,
        mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess")) as spawned,
    ):
        for name in _SCORERS:
            _score(name, payload)
    _check(
        connect.call_count == 0 and spawned.call_count == 0,
        "no scorer opens a socket or starts a subprocess -- execution belongs to the target",
        errors,
    )


def _check_every_shipped_rule_is_advisory(errors: list[str]) -> None:
    with open(_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    rules = (config.get("gate") or {}).get("rules") or []
    ours = [rule for rule in rules if rule.get("score") in _SCORERS]
    _check(len(ours) == len(_SCORERS), f"the shipped config gates all four scorers (found {len(ours)})", errors)
    _check(
        all(rule.get("report_only") is True for rule in ours),
        "every shipped gate rule for this capability is advisory, so no uncalibrated "
        f"threshold blocks a run (observed {[r.get('report_only') for r in ours]})",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_execution_is_gated(errors)
    _check_the_sandbox_really_executes(errors)
    _check_a_red_suite_cannot_claim_the_kill(errors)
    _check_absent_evidence_is_not_a_zero(errors)
    _check_both_denominators_are_emitted(errors)
    _check_scorers_are_pure(errors)
    _check_every_shipped_rule_is_advisory(errors)
    return report(logger, "F-065", errors)


if __name__ == "__main__":
    sys.exit(main())
