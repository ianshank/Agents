#!/usr/bin/env python3
"""Validation script for F-020 - Weighted / ensemble scoring.

Checks:
    1. ``CompositeScorer`` is registered as ``"weighted"`` with aliases
       ``"composite"`` and ``"ensemble"``.
    2. The weighted mean of child values is computed from configured weights.
    3. The per-child breakdown is stored in ``ScoreResult.metadata['components']``.
    4. The breakdown survives a ``RunResult.to_dict()`` round-trip (the C1 fix).
    5. Existing scorers remain registered.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    from eval_harness.core.types import (
        EvalItem,
        ItemResult,
        RunContext,
        RunResult,
        ScoreAggregate,
        TargetOutput,
    )
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()

    # 1. registration + aliases
    _check("weighted" in SCORERS, "CompositeScorer registered as 'weighted'", errors)
    for alias in ("composite", "ensemble"):
        _check(alias in SCORERS, f"alias '{alias}' registered", errors)
        _check(SCORERS.resolve(alias) == "weighted", f"alias '{alias}' resolves to 'weighted'", errors)

    # 2-3. weighted mean + breakdown
    try:
        # contains -> 1.0 (weight 3); exact_match vs different expected -> 0.0 (weight 1)
        # expected weighted value = (3*1.0 + 1*0.0) / 4 = 0.75
        scorer = SCORERS.create(
            "weighted",
            {
                "components": [
                    {"type": "contains", "params": {"substring": "ok"}, "weight": 3},
                    {"type": "exact_match", "params": {}, "weight": 1},
                ],
                "pass_threshold": 0.5,
            },
        )
        item = EvalItem(id="i1", inputs={}, expected="nope")
        out = TargetOutput(output="ok")
        res = scorer.score(item, out, RunContext(config=None))
        _check(abs(res.value - 0.75) < 1e-9, f"weighted value == 0.75 (got {res.value})", errors)
        _check(res.passed is True, "pass_threshold drives composite passed=True", errors)
        comps = res.metadata.get("components", [])
        _check(len(comps) == 2, "two components in metadata breakdown", errors)
        _check(
            comps[0]["weight"] == 3.0 and comps[0]["value"] == 1.0,
            "first component records weight and value",
            errors,
        )

        # 4. breakdown survives RunResult.to_dict() round-trip (C1)
        run = RunResult(
            run_id="r",
            config_name="c",
            items=[ItemResult(item=item, output=out, scores=[res])],
            aggregate={"weighted": ScoreAggregate(count=1, mean=res.value, pass_rate=1.0)},
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        dumped = run.to_dict()
        score_dict = dumped["items"][0]["scores"][0]
        _check(
            "metadata" in score_dict and score_dict["metadata"].get("components"),
            "composite breakdown survives RunResult.to_dict() (C1 fix)",
            errors,
        )
    except Exception as exc:
        errors.append(f"CompositeScorer scoring failed: {exc}")
        logger.error("CompositeScorer scoring failed: %s", exc)

    # 5. existing scorers intact
    for name in ("exact_match", "regex_match", "contains", "json_keys", "llm_judge"):
        _check(name in SCORERS, f"existing scorer '{name}' still registered", errors)

    return report(logger, "F-020", errors)


if __name__ == "__main__":
    sys.exit(main())
