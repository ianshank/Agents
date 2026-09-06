"""Shared JudgeCalibrationReport / probe fixtures for feature validators."""

from __future__ import annotations

from agent_core import (
    REPORT_SCHEMA_VERSION,
    JudgeCalibrationReport,
    OrderProbeResult,
    VerbosityProbeResult,
)

PASSING_VERBOSITY = VerbosityProbeResult(
    n=10,
    ties=0,
    concise_wins=5,
    expanded_wins=5,
    expanded_win_rate=0.5,
    preference_delta=0.0,
    ci_low=0.2,
    ci_high=0.8,
    passes=True,
)

PASSING_ORDER = OrderProbeResult(
    n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True
)

FAILING_ORDER = OrderProbeResult(
    n=10, flips=8, flip_rate=0.8, ci_low=0.5, ci_high=0.9, passes=False
)


def mk_report(
    order_flip: OrderProbeResult | None = None,
    *,
    agreement_may_gate: bool = True,
    artifact_id: str = "a",
    judge_id: str = "j",
) -> JudgeCalibrationReport:
    """Build a report with a passing verbosity probe and the given order probe."""
    return JudgeCalibrationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        judge_id=judge_id,
        artifact_id=artifact_id,
        n_total=100,
        n_codeterminate=90,
        percent_agreement=0.9,
        kappa=0.85,
        directional_only=False,
        agreement_may_gate=agreement_may_gate,
        order_flip=order_flip if order_flip is not None else PASSING_ORDER,
        verbosity=PASSING_VERBOSITY,
        self_preference=None,
        canary_pass_rate=1.0,
    )


def authorising_report(*, artifact_id: str = "run-1") -> JudgeCalibrationReport:
    """A may_gate=True report matching *artifact_id* (for positive gating checks)."""
    return mk_report(PASSING_ORDER, artifact_id=artifact_id, judge_id="j1")
