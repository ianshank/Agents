#!/usr/bin/env python3
"""Validation script for F-066 - Enforce judge-gate authorisation via real reports.

Opaque ``calibration_artifact_id`` strings alone must not authorise blocking
judge-backed gates. A resolvable ``JudgeCalibrationReport`` (via ``report=``,
``load_report=``, or ``judge_calibration.report_path``) must pass
``require_report_to_gate`` before gating is allowed.

Checks:
    1.  ``JudgeCalibrationGateConfig`` accepts optional ``report_path``.
    2.  ``require_calibration_for_judge_gating`` refuses an opaque ID alone.
    3.  Passing ``report=`` with a matching, authorising report succeeds.
    4.  ``report_path`` load + ``require_report_to_gate`` succeeds for a matching ID.
    5.  A may_gate=False report is refused (failing check named).
    6.  JSON load/dump round-trip preserves may_gate and artifact_id.
    7.  Demo and example configs that gate on a judge name a report_path whose
        file exists relative to the repo root.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS, os.path.join(_ROOT, "src"), os.path.join(_ROOT, "agent-core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _calibration_fixtures import authorising_report
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def _schema_version() -> str:
    from eval_harness.config.models import SCHEMA_VERSION

    return SCHEMA_VERSION




def main() -> int:
    configure_logging()
    errors: list[str] = []

    from agent_core import dump_judge_calibration_report, load_judge_calibration_report

    from eval_harness.config.models import EvalConfig, JudgeCalibrationGateConfig
    from eval_harness.gating import require_calibration_for_judge_gating
    from eval_harness.plugins import SCORERS, bootstrap

    bootstrap()

    gate_cfg = JudgeCalibrationGateConfig(
        calibration_artifact_id="run-1",
        report_path="some/path.json",
    )
    _check(
        gate_cfg.report_path == "some/path.json",
        "JudgeCalibrationGateConfig accepts report_path",
        errors,
    )

    gated = EvalConfig.model_validate(
        {
            "schema_version": _schema_version(),
            "dataset": {"type": "inline", "params": {"items": []}},
            "target": {"type": "echo"},
            "judge": {"type": "mock", "params": {}},
            "gate": {"rules": [{"score": "quality", "metric": "mean", "min": 0.5}]},
            "judge_calibration": {"calibration_artifact_id": "run-1"},
        }
    )
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    try:
        require_calibration_for_judge_gating(gated, scorers)
        _check(False, "opaque calibration_artifact_id alone is refused", errors)
    except ValueError as exc:
        _check(
            "no JudgeCalibrationReport was resolved" in str(exc),
            "opaque calibration_artifact_id alone is refused",
            errors,
        )

    require_calibration_for_judge_gating(gated, scorers, report=authorising_report(artifact_id="run-1"))
    _check(True, "report= with matching authorising report succeeds", errors)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cal.json"
        dump_judge_calibration_report(authorising_report(artifact_id="run-1"), path)
        with_path = EvalConfig.model_validate(
            {
                **gated.model_dump(mode="json"),
                "judge_calibration": {
                    "calibration_artifact_id": "run-1",
                    "report_path": str(path),
                },
            }
        )
        require_calibration_for_judge_gating(with_path, scorers)
        _check(True, "report_path load authorises matching report", errors)

        failing = replace(authorising_report(artifact_id="run-1"), agreement_may_gate=False)
        dump_judge_calibration_report(failing, path)
        try:
            require_calibration_for_judge_gating(with_path, scorers)
            _check(False, "may_gate=False report is refused", errors)
        except ValueError as exc:
            msg = str(exc).lower()
            _check(
                "may_gate" in msg or "failing" in msg or "agreement" in msg,
                "may_gate=False report is refused",
                errors,
            )

        dump_judge_calibration_report(authorising_report(artifact_id="round"), path)
        loaded = load_judge_calibration_report(path)
        _check(
            loaded.artifact_id == "round" and loaded.may_gate is True,
            "JSON round-trip preserves artifact_id and may_gate",
            errors,
        )

    for rel in (
        "demo/fixtures/demo-mock-judge-calibration-0000.json",
        "config/fixtures/example-offline-calibration-2026-08-18.json",
    ):
        _check(Path(_ROOT, rel).is_file(), f"fixture exists: {rel}", errors)

    for rel, expected_substr in (
        (
            "demo/configs/eval.pass.yaml",
            "demo/fixtures/demo-mock-judge-calibration-0000.json",
        ),
        (
            "demo/configs/eval.fail.yaml",
            "demo/fixtures/demo-mock-judge-calibration-0000.json",
        ),
        (
            "config/eval.example.yaml",
            "config/fixtures/example-offline-calibration-2026-08-18.json",
        ),
    ):
        text = Path(_ROOT, rel).read_text(encoding="utf-8")
        _check(
            expected_substr in text,
            f"{rel} names report_path relative to repo root",
            errors,
        )

    return report(logger, "F-066", errors)


if __name__ == "__main__":
    raise SystemExit(main())
