"""F-066: blocking judge gates require a real JudgeCalibrationReport, not an opaque ID."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.config.models import EvalConfig
from eval_harness.gating import require_calibration_for_judge_gating
from eval_harness.plugins import SCORERS

from tests.test_agent_core_adapter import _calibration_report


def _schema_version() -> str:
    from eval_harness.config.models import SCHEMA_VERSION

    return SCHEMA_VERSION


def _gated_judge_config(**calibration: object) -> EvalConfig:
    payload: dict = {
        "schema_version": _schema_version(),
        "dataset": {"type": "inline", "params": {"items": []}},
        "target": {"type": "echo"},
        "judge": {"type": "mock", "params": {}},
        "scorers": [{"type": "llm_judge", "params": {"name": "quality"}}],
        "gate": {"rules": [{"score": "quality", "metric": "mean", "min": 0.5}]},
    }
    if calibration:
        payload["judge_calibration"] = calibration
    return EvalConfig.model_validate(payload)


def test_opaque_artifact_id_alone_is_refused() -> None:
    config = _gated_judge_config(calibration_artifact_id="anything")
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    with pytest.raises(ValueError, match="no JudgeCalibrationReport was resolved"):
        require_calibration_for_judge_gating(config, scorers)


def test_report_kwarg_authorises_gating() -> None:
    config = _gated_judge_config(calibration_artifact_id="run-123")
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    require_calibration_for_judge_gating(
        config, scorers, report=_calibration_report(artifact_id="run-123")
    )


def test_load_report_injection_authorises_gating() -> None:
    config = _gated_judge_config(calibration_artifact_id="run-123")
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]

    def _load(artifact_id: str) -> object:
        return _calibration_report(artifact_id=artifact_id)

    require_calibration_for_judge_gating(config, scorers, load_report=_load)


def test_report_path_authorises_gating(tmp_path: Path) -> None:
    from agent_core import dump_judge_calibration_report

    report = _calibration_report(artifact_id="run-path-1")
    path = tmp_path / "cal.json"
    dump_judge_calibration_report(report, path)
    config = _gated_judge_config(
        calibration_artifact_id="run-path-1",
        report_path=str(path),
    )
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    require_calibration_for_judge_gating(config, scorers)


def test_report_path_id_mismatch_is_refused(tmp_path: Path) -> None:
    from agent_core import dump_judge_calibration_report

    report = _calibration_report(artifact_id="other-id")
    path = tmp_path / "cal.json"
    dump_judge_calibration_report(report, path)
    config = _gated_judge_config(
        calibration_artifact_id="run-path-1",
        report_path=str(path),
    )
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    with pytest.raises(ValueError, match="artifact_id"):
        require_calibration_for_judge_gating(config, scorers)


def test_may_gate_false_is_refused() -> None:
    config = _gated_judge_config(calibration_artifact_id="run-123")
    scorers = [SCORERS.create("llm_judge", {"name": "quality"})]
    with pytest.raises(ValueError, match="may_gate|failing|agreement"):
        require_calibration_for_judge_gating(
            config,
            scorers,
            report=_calibration_report(artifact_id="run-123", agreement_may_gate=False),
        )


def test_json_round_trip_preserves_may_gate(tmp_path: Path) -> None:
    from agent_core import (
        dump_judge_calibration_report,
        load_judge_calibration_report,
    )

    original = _calibration_report(artifact_id="round-trip")
    path = tmp_path / "round.json"
    dump_judge_calibration_report(original, path)
    loaded = load_judge_calibration_report(path)
    assert loaded.artifact_id == "round-trip"
    assert loaded.may_gate is True
    assert loaded.failing_checks == ()
