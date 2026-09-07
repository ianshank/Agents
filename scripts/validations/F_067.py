#!/usr/bin/env python3
"""Validation script for F-067 — RCA evaluation matrix (synthetic scope).

Implements ``openspec/changes/add-rca-eval-matrix`` task 7.1. Every check below is
established by RUNNING the thing it describes (the F-063 lesson): the corpus is
regenerated, the baseline target is run over it, and the scorers are asked what they
make of real diagnoses.

Checks:
1.  Load-time rejection: an item with no candidate set, or timestamps with no declared
    timezone, is refused — never silently scored against a singleton set or compared in
    an implicit local zone.
2.  A timezone-shifted onset (same wall clock, different declared zone) scores OUTSIDE
    tolerance, with both instants recorded normalised to UTC.
3.  Correct abstention on an unanswerable item scores correct; a confident guess is
    penalised and counted as a false accusation; abstaining on an answerable item is
    not free.
4.  The max-|Z| baseline runs on the same corpus: it is a registered deterministic
    target, and the shipped config evaluates it over the frozen corpus's identical item
    set.
5.  The committed corpus regenerates byte-identically, and the baseline's measured
    per-cell accuracy stays inside the calibrated bands (the corpus's difficulty is a
    gated measurement, not a claim).
6.  Every shipped gate rule for this capability is advisory (report_only), so no
    uncalibrated threshold blocks a run.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from eval_harness.core.types import ScoreResult

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
sys.path.insert(0, PROJECT_ROOT)

#: The five scorers this feature registers.
_SCORERS = (
    "rca_ac_at_k",
    "rca_component_match",
    "rca_onset_within_tolerance",
    "rca_abstention_correctness",
    "rca_false_accusation_rate",
)

#: The config whose gate rules must all be advisory.
_CONFIG = os.path.join(PROJECT_ROOT, "config", "rca_eval.yaml")

#: The frozen corpus this capability ships.
_CORPUS = os.path.join(PROJECT_ROOT, "corpora", "rca", "v1")


def _score(name: str, item_inputs: dict, expected: object, output: object) -> ScoreResult:
    from eval_harness.core.types import EvalItem, RunContext, TargetOutput
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()
    scorer = SCORERS.create(name, {})
    return scorer.score(
        EvalItem(id="v", inputs=item_inputs, expected=expected),
        TargetOutput(output=output),
        RunContext(config=None),
    )


def _check_load_rejection(errors: list[str]) -> None:
    from _rca_corpus_lib import validate_item

    no_candidates = {"instance_id": "x", "timezone": "UTC", "correct": ["a"], "onset": "2026-03-04T11:42:00+00:00"}
    _check(
        any("candidates" in p for p in validate_item(no_candidates)),
        "an item with no candidate set is rejected at load (never scored against a set of one)",
        errors,
    )
    no_tz = {"instance_id": "x", "candidates": ["a"], "correct": [], "onset": "2026-03-04T11:42:00+00:00"}
    _check(
        any("timezone" in p for p in validate_item(no_tz)),
        "an item with timestamps and no declared timezone is rejected at load",
        errors,
    )


def _check_timezone_shifted_onset_is_wrong(errors: list[str]) -> None:
    inputs = {"candidates": ["svc-a"], "onset": "2026-03-04T11:42:00+08:00", "timezone": "UTC+08:00"}
    shifted = _score(
        "rca_onset_within_tolerance", inputs, ["svc-a"], {"ranked": ["svc-a"], "onset": "2026-03-04T11:42:00+00:00"}
    )
    _check(
        shifted.passed is False,
        "a wall-clock match in the wrong declared zone scores outside tolerance",
        errors,
    )
    metadata = getattr(shifted, "metadata", {})
    _check(
        str(metadata.get("claimed_onset_utc", "")).endswith("+00:00")
        and str(metadata.get("confirmed_onset_utc", "")).endswith("+00:00"),
        "the evidence records both instants normalised to a single timezone",
        errors,
    )
    within = _score(
        "rca_onset_within_tolerance", inputs, ["svc-a"], {"ranked": ["svc-a"], "onset": "2026-03-04T11:50:00+08:00"}
    )
    _check(within.passed is True, "an onset within the configured tolerance scores correct", errors)


def _check_abstention_semantics(errors: list[str]) -> None:
    unanswerable = {"candidates": ["svc-a", "svc-b"]}
    decline = _score("rca_abstention_correctness", unanswerable, [], {"abstain": True})
    _check(
        decline.passed is True,
        "correct abstention on an unanswerable item scores correct",
        errors,
    )
    guess = _score("rca_abstention_correctness", unanswerable, [], {"ranked": ["svc-a"]})
    _check(guess.passed is False, "a confident guess on an unanswerable item is penalised", errors)
    accusation = _score("rca_false_accusation_rate", unanswerable, [], {"ranked": ["svc-a"]})
    _check(
        getattr(accusation, "value", None) == 1.0,
        "a named cause on an unanswerable item is counted as a false accusation",
        errors,
    )
    free = _score("rca_abstention_correctness", unanswerable, ["svc-a"], {"abstain": True})
    _check(free.passed is False, "abstaining on an answerable item is not free", errors)
    na = _score("rca_ac_at_k", unanswerable, [], {"abstain": True})
    _check(na.passed is None, "rca_ac_at_k reports not-applicable (not zero) on an unanswerable item", errors)


def _check_the_baseline_runs_on_the_same_corpus(errors: list[str]) -> None:
    import json

    from eval_harness.core.types import EvalItem
    from eval_harness.plugins import TARGETS, bootstrap

    bootstrap()
    target = TARGETS.create("rca_maxz", {})
    _check(target.is_deterministic() is True, "the baseline declares itself deterministic", errors)

    with open(os.path.join(_CORPUS, "eval", "items.jsonl"), encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    _check(bool(records), "the frozen corpus ships an eval dataset", errors)

    # The baseline runs over the identical item set the config evaluates — no subset,
    # no separate fixture. Two runs must agree exactly (no clock, no RNG, no network).
    first = [target.run(EvalItem(id=r["id"], inputs=r["inputs"], expected=r.get("expected"))).output for r in records]
    second = [target.run(EvalItem(id=r["id"], inputs=r["inputs"], expected=r.get("expected"))).output for r in records]
    _check(first == second, "the baseline is deterministic over the frozen corpus", errors)
    diagnosed = sum(1 for out in first if isinstance(out, dict) and out.get("ranked"))
    declined = sum(1 for out in first if isinstance(out, dict) and out.get("abstain"))
    _check(
        diagnosed > 0 and declined > 0,
        f"the baseline diagnoses some items and declines others on the real corpus "
        f"(diagnosed={diagnosed}, declined={declined}) — a baseline that always guesses "
        "or always declines measures nothing",
        errors,
    )


def _check_corpus_regeneration_and_bands(errors: list[str]) -> None:
    from gen_rca_corpus import check_corpus

    problems = check_corpus(__import__("pathlib").Path(_CORPUS))
    _check(
        not problems,
        f"the committed corpus regenerates byte-identically and its difficulty bands hold (problems: {problems[:2]})",
        errors,
    )


def _check_every_shipped_rule_is_advisory(errors: list[str]) -> None:
    with open(_CONFIG, encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    rules = (config.get("gate") or {}).get("rules") or []
    ours = [rule for rule in rules if rule.get("score") in _SCORERS]
    _check(bool(ours), "the shipped config gates this capability's scorers", errors)
    _check(
        all(rule.get("report_only") is True for rule in ours),
        "every shipped gate rule for this capability is advisory, so no uncalibrated "
        f"threshold blocks a run (observed {[r.get('report_only') for r in ours]})",
        errors,
    )


def main() -> int:
    configure_logging()
    errors: list[str] = []
    _check_load_rejection(errors)
    _check_timezone_shifted_onset_is_wrong(errors)
    _check_abstention_semantics(errors)
    _check_the_baseline_runs_on_the_same_corpus(errors)
    _check_corpus_regeneration_and_bands(errors)
    _check_every_shipped_rule_is_advisory(errors)
    return report(logger, "F-067", errors)


if __name__ == "__main__":
    sys.exit(main())
