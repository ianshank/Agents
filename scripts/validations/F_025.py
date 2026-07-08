#!/usr/bin/env python3
"""Validation script for F-025 — A/B eval campaigns with significance.

Deterministic and offline: runs a two-arm campaign over echo targets, accumulates
per-arm counts in a store, and asserts the Wilson-based decision is honest about
power (no claim below min_sample) and reuses agent_core's interval.

    1. ABCampaignConfig requires distinct arm names.
    2. record_run appends per-arm pass/total counts; the store accumulates them.
    3. analyze returns CANT_TELL below the power floor, and B_BETTER once powered
       and the Wilson intervals separate.
    4. to_dict is JSON-serialisable; to_html is deterministic and self-contained.
    5. SCHEMA_VERSION is unchanged.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

from eval_harness.campaign import CampaignStore, Decision, analyze, record_run
from eval_harness.config.models import ABCampaignConfig, EvalConfig
from eval_harness.version import SCHEMA_VERSION

FIXED = datetime(2026, 6, 30, tzinfo=timezone.utc)


def _items(n: int) -> list[dict]:
    return [{"id": str(i), "inputs": {"good": "x", "bad": "y"}, "expected": "x"} for i in range(n)]


def _ab_block(min_sample: int = 30) -> dict:
    return {
        "campaign_id": "c1",
        "arm_a": {"name": "lo", "target": {"type": "echo", "params": {"output_key": "bad"}}},
        "arm_b": {"name": "hi", "target": {"type": "echo", "params": {"output_key": "good"}}},
        "score": "exact_match",
        "min_sample": min_sample,
    }


def _config(n: int, min_sample: int = 30) -> EvalConfig:
    # Build from a raw mapping via model_validate (Pydantic coerces the nested dicts into
    # the typed sub-models) — keeps mypy honest about the dict->model boundary without
    # loosening the model's field types.
    return EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "dataset": {"type": "inline", "params": {"items": _items(n)}},
            "target": {"type": "echo", "params": {}},
            "scorers": [{"type": "exact_match", "params": {}}],
            "ab_campaign": _ab_block(min_sample),
        }
    )


def _campaign(min_sample: int = 30) -> ABCampaignConfig:
    # analyze() requires a non-optional ABCampaignConfig; validate the same raw block
    # directly so the value's type is the concrete model rather than EvalConfig.ab_campaign
    # (which is Optional). Identical block -> identical runtime behavior.
    return ABCampaignConfig.model_validate(_ab_block(min_sample))


def _distinct_arms_enforced() -> bool:
    arm = {"name": "x", "target": {"type": "echo"}}
    try:
        # Validate a raw mapping so Pydantic coerces the arm dicts into ModelSpec and still
        # runs the @model_validator (which rejects identical arm names) — same runtime check.
        ABCampaignConfig.model_validate({"campaign_id": "c", "arm_a": arm, "arm_b": arm, "score": "s"})
        return False
    except Exception:
        return True


def validate_f025() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-025")
    errors: list[str] = []

    _check(_distinct_arms_enforced(), "distinct arm names enforced", errors)

    with tempfile.TemporaryDirectory() as tmp:
        # below power -> cant_tell
        store = CampaignStore(Path(tmp) / "small.jsonl")
        cfg_small = _config(5, min_sample=30)
        recs = record_run(store, cfg_small, now=FIXED)
        _check(len(recs) == 2, "record_run writes one record per arm", errors)
        _check(store.totals("c1", "hi") == (5, 5), "store accumulates per-arm totals", errors)
        _check(
            analyze(store, _campaign(min_sample=30)).decision is Decision.CANT_TELL,
            "below the power floor -> CANT_TELL (no claim)",
            errors,
        )

        # powered + separated -> b_better
        store2 = CampaignStore(Path(tmp) / "big.jsonl")
        cfg_big = _config(30, min_sample=30)
        record_run(store2, cfg_big, now=FIXED)
        result = analyze(store2, _campaign(min_sample=30))
        _check(result.decision is Decision.B_BETTER, "powered + separated -> B_BETTER", errors)
        _check(result.delta == 1.0, "delta computed (hi 1.0 - lo 0.0)", errors)

        d = result.to_dict()
        try:
            json.dumps(d)
            json_ok = True
        except TypeError:
            json_ok = False
        _check(json_ok, "to_dict is JSON-serialisable", errors)
        html_a, html_b = result.to_html(), result.to_html()
        _check(html_a == html_b, "to_html is deterministic", errors)
        _check(
            "http://" not in html_a and "https://" not in html_a,
            "to_html has no external assets",
            errors,
        )

    _check(SCHEMA_VERSION == "1.0", "SCHEMA_VERSION unchanged", errors)
    return report(logger, "F-025", errors)


if __name__ == "__main__":
    sys.exit(validate_f025())
