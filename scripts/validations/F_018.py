#!/usr/bin/env python3
"""Validation script for F-018 – Parallel item execution.

Checks:
    1. ``RunSettings`` accepts and validates ``max_workers``.
    2. Sequential (max_workers=1) and parallel (max_workers=4) produce
       identical aggregate means.
    3. ``max_workers=0`` is rejected by the validator.

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup — same convention as F_001 .. F_016
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = PROJECT_ROOT / "src"
for _p in (str(PROJECT_ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> int:
    """Run all F-018 validation checks."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    from eval_harness.config import load_config_dict
    from eval_harness.config.models import RunSettings
    from eval_harness.engine import EvalEngine
    from eval_harness.langfuse_client import NullLangfuseClient
    from eval_harness.plugins import bootstrap
    from eval_harness.version import SCHEMA_VERSION

    bootstrap()

    errors: list[str] = []

    # 1. RunSettings accepts max_workers
    try:
        settings = RunSettings(max_workers=4)
        assert settings.max_workers == 4, "max_workers not set to 4"
        logger.info("OK: RunSettings accepts max_workers=4")
    except Exception as exc:
        errors.append(f"RunSettings(max_workers=4) failed: {exc}")
        logger.error("RunSettings(max_workers=4) failed: %s", exc)

    # 2. max_workers=0 rejected
    try:
        RunSettings(max_workers=0)
        errors.append("RunSettings(max_workers=0) should have been rejected")
        logger.error("RunSettings(max_workers=0) was NOT rejected")
    except Exception:
        logger.info("OK: RunSettings(max_workers=0) correctly rejected")

    # 3. Sequential and parallel produce identical aggregate means
    cfg_base = {
        "schema_version": SCHEMA_VERSION,
        "run": {"name": "f018", "run_id": "f018-val", "seed": 99},
        "dataset": {
            "type": "inline",
            "params": {
                "items": [
                    {"id": str(i), "inputs": {"q": f"q{i}"}, "expected": f"q{i}"}
                    for i in range(8)
                ]
            },
        },
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "acc"}}],
        "sinks": [],
    }

    from datetime import datetime, timezone

    def _clock():
        return datetime(2026, 6, 22, tzinfo=timezone.utc)

    try:
        # Sequential
        cfg_seq = dict(cfg_base)
        cfg_seq["run"] = {**cfg_base["run"], "max_workers": 1}
        config_seq = load_config_dict(cfg_seq)
        engine_seq = EvalEngine.from_config(config_seq, langfuse_client=NullLangfuseClient())
        engine_seq.clock = _clock
        run_seq = engine_seq.run()

        # Parallel
        cfg_par = dict(cfg_base)
        cfg_par["run"] = {**cfg_base["run"], "max_workers": 4}
        config_par = load_config_dict(cfg_par)
        engine_par = EvalEngine.from_config(config_par, langfuse_client=NullLangfuseClient())
        engine_par.clock = _clock
        run_par = engine_par.run()

        # Compare aggregates
        for key in run_seq.aggregate:
            seq_mean = run_seq.aggregate[key].mean
            par_mean = run_par.aggregate[key].mean
            if abs(seq_mean - par_mean) > 1e-9:
                msg = f"Aggregate mismatch for {key}: seq={seq_mean}, par={par_mean}"
                errors.append(msg)
                logger.error(msg)

        if len(run_seq.items) != len(run_par.items):
            msg = f"Item count mismatch: seq={len(run_seq.items)}, par={len(run_par.items)}"
            errors.append(msg)
            logger.error(msg)

        if not errors or len(errors) == 0:
            logger.info("OK: Sequential and parallel aggregates are identical")
    except Exception as exc:
        errors.append(f"Sequential/parallel comparison failed: {exc}")
        logger.error("Sequential/parallel comparison failed: %s", exc)

    # Summary
    if errors:
        logger.error("FAIL: F-018 with %d error(s):", len(errors))
        for err in errors:
            logger.error("  • %s", err)
        return 1

    logger.info("PASS: F-018 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
