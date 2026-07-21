#!/usr/bin/env python3
"""Validation script for F-024 — multi-model comparison.

Deterministic and offline (no network): runs the same inline dataset against two
echo "models" and asserts the comparison ranks them, computes deltas vs a
baseline, and renders a self-contained deterministic HTML report.

    1. ComparisonConfig validates (>=2 models, unique names, baseline must exist).
    2. run_comparison ranks the correct model first and computes baseline deltas.
    3. to_dict is JSON-serialisable; to_html is deterministic with no external assets.
    4. EvalConfig carries the optional comparison block; SCHEMA_VERSION unchanged.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import json
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from _common import check as _check
from _common import configure_logging, report

from eval_harness.comparison import run_comparison
from eval_harness.config.models import ComparisonConfig, EvalConfig
from eval_harness.version import SCHEMA_VERSION

_ITEMS = [{"id": "1", "inputs": {"a": "x", "b": "y"}, "expected": "x"}]


def _config() -> EvalConfig:
    return EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "cmp"},
            "dataset": {"type": "inline", "params": {"items": _ITEMS}},
            "target": {"type": "echo", "params": {}},
            "scorers": [{"type": "exact_match", "params": {}}],
            "comparison": {
                "baseline": "good",
                "models": [
                    {"name": "good", "target": {"type": "echo", "params": {"output_key": "a"}}},
                    {"name": "bad", "target": {"type": "echo", "params": {"output_key": "b"}}},
                ],
            },
        }
    )


def _raises(**kwargs) -> bool:
    try:
        ComparisonConfig(**kwargs)
        return False
    except Exception:
        return True


def validate_f024() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-024")
    errors: list[str] = []

    echo = {"type": "echo"}
    _check(_raises(models=[{"name": "a", "target": echo}]), "requires >= 2 models", errors)
    _check(
        _raises(models=[{"name": "a", "target": echo}, {"name": "a", "target": echo}]),
        "model names must be unique",
        errors,
    )
    _check(
        _raises(models=[{"name": "a", "target": echo}, {"name": "b", "target": echo}], baseline="zzz"),
        "baseline must be a model name",
        errors,
    )

    result = run_comparison(_config())
    _check(result.overall_ranking == ["good", "bad"], "ranks the correct model first", errors)
    cmp = result.comparisons[0]
    _check(cmp.values == {"good": 1.0, "bad": 0.0}, "per-model metric values correct", errors)
    _check(cmp.deltas == {"good": 0.0, "bad": -1.0}, "baseline deltas correct", errors)

    d = result.to_dict()
    _check(set(d["runs"]) == {"good", "bad"}, "to_dict carries per-model runs", errors)
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

    _check(_config().comparison is not None, "EvalConfig carries comparison block", errors)
    _check(SCHEMA_VERSION == "1.0", "SCHEMA_VERSION unchanged", errors)

    return report(logger, "F-024", errors)


if __name__ == "__main__":
    sys.exit(validate_f024())
