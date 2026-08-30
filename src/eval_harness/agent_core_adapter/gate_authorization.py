"""Judge-calibration-report gate authorization.

Split from ``agent_core_adapter/__init__.py`` purely to stay under the
500-line file budget (see ``calibration.py``'s module docstring for the
sibling-module precedent this package already established).
"""

from __future__ import annotations

from agent_core import JudgeCalibrationReport


def _describe_failing_check(report: JudgeCalibrationReport, name: str) -> str:
    """Append a probe's degenerate reason to its bare check name when present.

    ``failing_checks`` only ever names a check (``"order_flip"``, ...); the probe
    it points at may separately be undersized (``.degenerate`` set) rather than
    genuinely biased. Without this, a caller has to re-fetch the full report to
    tell those two apart. ``"agreement_or_power"`` has no corresponding probe, so
    ``getattr`` falls through to the bare name with no special-casing needed.
    """
    probe = getattr(report, name, None)
    reason = getattr(probe, "degenerate", None)
    return f"{name} ({reason})" if reason else name


def require_report_to_gate(report: JudgeCalibrationReport, expected_artifact_id: str) -> None:
    """Raise unless *report* authorises gating under *expected_artifact_id*.

    ``spec.md`` "Uncalibrated judges cannot gate releases": a judge stays advisory
    unless agreement, power and every configured bias tolerance pass
    (``report.may_gate``); the error names every failing check
    (``report.failing_checks``), not just a bare verdict. Also checks
    ``report.artifact_id == expected_artifact_id`` first, so a stale or mismatched
    report can't be substituted for the run named by a config's
    ``judge_calibration.calibration_artifact_id``
    (``eval_harness.config.models.JudgeCalibrationGateConfig``) without actually
    being that calibration run.
    """
    if report.artifact_id != expected_artifact_id:
        raise ValueError(
            f"calibration report artifact_id {report.artifact_id!r} does not match the "
            f"configured judge_calibration.calibration_artifact_id {expected_artifact_id!r}"
        )
    if not report.may_gate:
        reason = ", ".join(_describe_failing_check(report, name) for name in report.failing_checks) or "agreement/power"
        raise ValueError(f"judge calibration artifact {expected_artifact_id!r} does not authorise gating: {reason}")
