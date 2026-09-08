#!/usr/bin/env python3
"""Validation script for F-069 — agent-in-the-loop test generation (Deck B).

Every check below is established by RUNNING the thing it describes (the F-063
lesson). The pipeline target is constructed, a generator that only copies
``inputs.suite`` is refused the key, a holdout allowlist rejects train items, and
the shipped profile's gate rules are advisory.

Checks:
    1.  ``testgen_agent`` is a registered TargetRunner (not an ADR 0039 path).
    2.  The generator view does not contain ``inputs.suite`` (homework attack).
    3.  Train items fail closed when ``allowed_splits`` is holdout-only.
    4.  A missing generator fail-closes with structured empty evidence (ADR 0038).
    5.  A generated killing suite is executed in-process; F-065 scorers read it.
    6.  The shipped Deck B config is holdout-only and every gate rule is advisory.
    7.  ``generator_path`` is refused when the callable is outside the allowlist.
    8.  Deck A ``config/testgen_eval.yaml`` stays the corpus ``callable`` path.
    9.  The empty/null baseline yaml is holdout-only, advisory, and has no generator_path.
    10. Mutating nested ``obligations`` on the generator view does not poison the original.
    11. Execute still publishes empty ``TESTGEN_EVIDENCE_KEY`` when reference is missing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

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

_SCORERS = (
    "test_executability",
    "testgen_mutation_score",
    "testgen_green_on_correct",
    "requirement_obligation_recall",
)
_CONFIG = os.path.join(PROJECT_ROOT, "config", "testgen_agent_eval.yaml")
_EMPTY_CONFIG = os.path.join(PROJECT_ROOT, "config", "testgen_agent_empty_eval.yaml")
_DECK_A_CONFIG = os.path.join(PROJECT_ROOT, "config", "testgen_eval.yaml")
_KILLING = "from focal import add\n\ndef test_boundary():\n    assert add(2, 1) == -1\n"
_FOCAL = "def add(n, k):\n    if n < 2:\n        return n + k\n    return k - n\n"
_MUTANT = {
    "id": "M1",
    "kind": "relational",
    "equivalent": False,
    "source": "def add(n, k):\n    if n <= 2:\n        return n + k\n    return k - n\n",
    "differs_at": [1],
}


def _item_inputs(suite: str) -> dict[str, Any]:
    return {
        "focal_name": "add",
        "reference": _FOCAL,
        "suite": suite,
        "mutants": [_MUTANT],
        "obligations": [{"id": "OB-1", "witness_mutant": "M1"}],
        "grid": [[0, 0], [2, 1]],
    }


def _eval_item(split: str = "holdout", suite: str = "SECRET_CORPUS_SUITE") -> Any:
    from eval_harness.core.types import EvalItem

    return EvalItem(id="v", inputs=_item_inputs(suite), metadata={"split": split})


def _check_registered_name_is_not_an_allowlist_path(errors: list[str]) -> None:
    from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV
    from eval_harness.plugins import TARGETS, bootstrap

    bootstrap()
    saved = os.environ.get(CALLABLE_ALLOWLIST_ENV)
    os.environ[CALLABLE_ALLOWLIST_ENV] = "something_else"
    try:
        target = TARGETS.create("testgen_agent", {})
        constructed = target is not None
    except Exception:
        constructed = False
    finally:
        if saved is None:
            os.environ.pop(CALLABLE_ALLOWLIST_ENV, None)
        else:
            os.environ[CALLABLE_ALLOWLIST_ENV] = saved
    _check(
        constructed,
        "testgen_agent is constructed from the registry with no callable allowlist entry",
        errors,
    )


def _check_homework_attack(errors: list[str]) -> None:
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    seen: dict[str, Any] = {}

    def spy(view: Any) -> str:
        seen["suite"] = "suite" in view.inputs
        return _KILLING

    TestgenAgentTarget(generate=spy).run(_eval_item())
    _check(seen.get("suite") is False, "the generator view does not contain inputs.suite", errors)


def _check_holdout_allowlist(errors: list[str]) -> None:
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    out = TestgenAgentTarget(generate=lambda _view: _KILLING).run(_eval_item(split="train"))
    _check(
        out.error is not None and "train" in (out.error or ""),
        "a train item fail-closes when allowed_splits is holdout-only",
        errors,
    )


def _check_missing_generator_fail_closed(errors: list[str]) -> None:
    from eval_harness.core.types import TESTGEN_EVIDENCE_KEY
    from eval_harness.plugins import TARGETS, bootstrap

    bootstrap()
    out = TARGETS.create("testgen_agent", {}).run(_eval_item())
    payload = out.metadata.get(TESTGEN_EVIDENCE_KEY) or {}
    _check(
        out.error is not None and payload.get("collected") == 0,
        "a missing generator fail-closes with structured empty evidence",
        errors,
    )


def _check_generated_suite_is_executed(errors: list[str]) -> None:
    from eval_harness.core.types import TESTGEN_EVIDENCE_KEY, EvalItem, RunContext
    from eval_harness.plugins import SCORERS, bootstrap
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    bootstrap()
    out = TestgenAgentTarget(generate=lambda _view: _KILLING).run(_eval_item())
    payload = out.metadata.get(TESTGEN_EVIDENCE_KEY) or {}
    _check(
        payload.get("mutants", {}).get("killed") == 1,
        "a generated killing suite is executed and kills the mutant",
        errors,
    )
    scorer = SCORERS.create("testgen_mutation_score", {"denominator": "raw"})
    scored = scorer.score(EvalItem(id="v", inputs={}, expected=None), out, RunContext(config=None))
    _check(scored.value == 1.0, "F-065 mutation scorer reads the generated-suite evidence", errors)


def _check_shipped_profile_is_advisory_holdout(errors: list[str]) -> None:
    with open(_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = (config.get("target") or {}).get("params") or {}
    splits = params.get("allowed_splits") or []
    _check(
        splits == ["holdout"] and "train" not in splits,
        "the shipped Deck B profile allowlists holdout only (cannot train on holdout)",
        errors,
    )
    rules = (config.get("gate") or {}).get("rules") or []
    ours = [rule for rule in rules if rule.get("score") in _SCORERS]
    _check(len(ours) == len(_SCORERS), f"the shipped config gates all four scorers (found {len(ours)})", errors)
    _check(
        all(rule.get("report_only") is True for rule in ours),
        "every shipped Deck B gate rule is advisory",
        errors,
    )


def _check_deck_a_yaml_stays_callable(errors: list[str]) -> None:
    with open(_DECK_A_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    target = config.get("target") or {}
    params = target.get("params") or {}
    _check(
        target.get("type") == "callable" and params.get("path") == "eval_harness.targets.testgen:run_generated_suite",
        "Deck A config/testgen_eval.yaml stays the corpus callable path",
        errors,
    )


def _check_empty_baseline_yaml(errors: list[str]) -> None:
    with open(_EMPTY_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = (config.get("target") or {}).get("params") or {}
    splits = params.get("allowed_splits") or []
    _check(
        config.get("target", {}).get("type") == "testgen_agent"
        and splits == ["holdout"]
        and "generator_path" not in params,
        "the empty baseline is holdout-only testgen_agent with no generator_path",
        errors,
    )
    rules = (config.get("gate") or {}).get("rules") or []
    ours = [rule for rule in rules if rule.get("score") in _SCORERS]
    _check(
        bool(ours) and all(rule.get("report_only") is True for rule in ours),
        "every empty-baseline gate rule is advisory",
        errors,
    )


def _check_nested_view_is_isolated(errors: list[str]) -> None:
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    item = _eval_item()
    snapshot = list(item.inputs["obligations"])

    def spy(view: Any) -> str:
        obligations = view.inputs.get("obligations")
        if isinstance(obligations, list):
            obligations.append("MUTATED_BY_GENERATOR")
        return _KILLING

    out = TestgenAgentTarget(generate=spy).run(item)
    _check(
        out.error is None and item.inputs["obligations"] == snapshot,
        "mutating the generator view does not poison the original item",
        errors,
    )


def _check_execute_publishes_evidence_when_reference_missing(errors: list[str]) -> None:
    from eval_harness.core.types import TESTGEN_EVIDENCE_KEY
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    item = _eval_item()
    del item.inputs["reference"]
    out = TestgenAgentTarget(generate=lambda _view: _KILLING).run(item)
    payload = out.metadata.get(TESTGEN_EVIDENCE_KEY) or {}
    _check(
        out.error is not None and payload.get("collected") == 0,
        "execute still publishes empty evidence when reference is missing",
        errors,
    )


def _check_generator_path_is_allowlisted(errors: list[str]) -> None:
    from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV
    from eval_harness.targets.testgen_agent import TestgenAgentTarget

    saved = os.environ.get(CALLABLE_ALLOWLIST_ENV)
    os.environ[CALLABLE_ALLOWLIST_ENV] = "something_else"
    try:
        out = TestgenAgentTarget(generator_path="tests._testgen_agent_fixtures:killing_suite").run(_eval_item())
        refused = out.error is not None
    finally:
        if saved is None:
            os.environ.pop(CALLABLE_ALLOWLIST_ENV, None)
        else:
            os.environ[CALLABLE_ALLOWLIST_ENV] = saved
    _check(refused, "an unlisted generator_path is refused (ADR 0039)", errors)


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_registered_name_is_not_an_allowlist_path(errors)
    _check_homework_attack(errors)
    _check_holdout_allowlist(errors)
    _check_missing_generator_fail_closed(errors)
    _check_generated_suite_is_executed(errors)
    _check_shipped_profile_is_advisory_holdout(errors)
    _check_generator_path_is_allowlisted(errors)
    _check_deck_a_yaml_stays_callable(errors)
    _check_empty_baseline_yaml(errors)
    _check_nested_view_is_isolated(errors)
    _check_execute_publishes_evidence_when_reference_missing(errors)
    return report(logger, "F-069", errors)


if __name__ == "__main__":
    sys.exit(main())
