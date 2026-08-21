from typing import Any

import pytest

from agent_core.judge_calibration import (
    OrderProbeResult,
    SelfPreferenceResult,
    VerbosityProbeResult,
)
from agent_core.judge_calibration_report import (
    REPORT_SCHEMA_VERSION,
    JudgeCalibrationReport,
    build_judge_calibration_report,
)
from agent_core.pairwise import PairwiseItem


def _passing_order() -> OrderProbeResult:
    return OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True)


def _failing_order() -> OrderProbeResult:
    return OrderProbeResult(n=10, flips=8, flip_rate=0.8, ci_low=0.5, ci_high=0.9, passes=False)


def _passing_verbosity() -> VerbosityProbeResult:
    return VerbosityProbeResult(
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


def _passing_self_preference() -> SelfPreferenceResult:
    return SelfPreferenceResult(
        judge_family="gpt",
        same_family_n=10,
        same_family_win_rate=0.5,
        same_family_ci_low=0.2,
        same_family_ci_high=0.8,
        other_family_n=10,
        other_family_win_rate=0.5,
        other_family_ci_low=0.2,
        other_family_ci_high=0.8,
        delta=0.0,
        passes=True,
    )


def _failing_self_preference() -> SelfPreferenceResult:
    return SelfPreferenceResult(
        judge_family="gpt",
        same_family_n=10,
        same_family_win_rate=0.9,
        same_family_ci_low=0.6,
        same_family_ci_high=1.0,
        other_family_n=10,
        other_family_win_rate=0.1,
        other_family_ci_low=0.0,
        other_family_ci_high=0.4,
        delta=0.8,
        passes=False,
    )


def _failing_verbosity() -> VerbosityProbeResult:
    return VerbosityProbeResult(
        n=10,
        ties=0,
        concise_wins=1,
        expanded_wins=9,
        expanded_win_rate=0.9,
        preference_delta=0.4,
        ci_low=0.6,
        ci_high=1.0,
        passes=False,
    )


def _canary(item_id="c1", kind="known_equal", expected="tie") -> PairwiseItem:
    return PairwiseItem(
        item_id=item_id,
        prompt="p",
        answer_a="a",
        answer_b="b",
        family_a="gpt",
        family_b="claude",
        expected=expected,
        canary_kind=kind,
    )


def _report(**overrides: Any) -> JudgeCalibrationReport:
    defaults: dict[str, Any] = dict(
        judge_id="j1",
        artifact_id="art-1",
        n_total=100,
        n_codeterminate=90,
        percent_agreement=0.9,
        kappa=0.85,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=_passing_self_preference(),
        canary_pass_rate=1.0,
    )
    defaults.update(overrides)
    return JudgeCalibrationReport(schema_version=REPORT_SCHEMA_VERSION, **defaults)


# --- may_gate / failing_checks -------------------------------------------------


def test_may_gate_true_when_everything_passes():
    report = _report()
    assert report.may_gate is True
    assert report.failing_checks == ()


def test_may_gate_false_when_agreement_fails():
    report = _report(agreement_may_gate=False)
    assert report.may_gate is False
    assert "agreement_or_power" in report.failing_checks


def test_may_gate_false_when_order_flip_fails_even_with_good_agreement():
    """A biased judge stays advisory even if it clears its agreement floor."""
    report = _report(order_flip=_failing_order())
    assert report.may_gate is False
    assert report.failing_checks == ("order_flip",)


def test_may_gate_false_when_verbosity_fails():
    report = _report(verbosity=_failing_verbosity())
    assert report.may_gate is False
    assert report.failing_checks == ("verbosity",)


def test_may_gate_false_when_self_preference_fails():
    report = _report(self_preference=_failing_self_preference())
    assert report.may_gate is False
    assert report.failing_checks == ("self_preference",)


def test_may_gate_false_when_directional_only():
    report = _report(directional_only=True, agreement_may_gate=False)
    assert report.may_gate is False
    assert "agreement_or_power" in report.failing_checks


def test_failing_checks_names_every_failing_check_not_just_the_first():
    report = _report(order_flip=_failing_order(), agreement_may_gate=False)
    assert set(report.failing_checks) == {"agreement_or_power", "order_flip"}


def test_self_preference_none_is_not_a_failure():
    """When self-preference isn't applicable (family unknown), it must not
    silently block gating."""
    report = _report(self_preference=None)
    assert report.may_gate is True


def test_canary_pass_rate_does_not_affect_may_gate():
    """Canaries are diagnostic only per spec.md's ADDED Requirements."""
    report = _report(canary_pass_rate=0.0)
    assert report.may_gate is True


# --- build_judge_calibration_report --------------------------------------------


def test_build_computes_canary_pass_rate():
    canaries = [_canary("c1", "known_equal", "tie"), _canary("c2", "clearly_better", "a")]
    report = build_judge_calibration_report(
        "j1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=canaries,
        canary_verdicts=["tie", "b"],  # second one wrong
    )
    assert report.canary_pass_rate == 0.5
    assert report.schema_version == REPORT_SCHEMA_VERSION


def test_build_rejects_mismatched_canary_lengths():
    with pytest.raises(ValueError, match="equal length"):
        build_judge_calibration_report(
            "j1",
            "art-1",
            n_total=1,
            n_codeterminate=1,
            percent_agreement=1.0,
            kappa=1.0,
            directional_only=False,
            agreement_may_gate=True,
            order_flip=_passing_order(),
            verbosity=_passing_verbosity(),
            self_preference=None,
            canaries=[_canary()],
            canary_verdicts=["tie", "a"],
        )


def test_build_rejects_empty_canaries():
    with pytest.raises(ValueError, match="no canaries"):
        build_judge_calibration_report(
            "j1",
            "art-1",
            n_total=1,
            n_codeterminate=1,
            percent_agreement=1.0,
            kappa=1.0,
            directional_only=False,
            agreement_may_gate=True,
            order_flip=_passing_order(),
            verbosity=_passing_verbosity(),
            self_preference=None,
            canaries=[],
            canary_verdicts=[],
        )


# --- panel-only fields (F-059, add-panel-judge) --------------------------------


def test_panel_fields_default_empty_for_a_single_judge_report():
    report = _report()
    assert report.pairwise_member_kappa == ()
    assert report.abstention_rate is None
    assert report.member_families == ()


def test_panel_fields_do_not_affect_may_gate():
    """Panel-only diagnostics are informational, like canary_pass_rate -- not a
    gating condition (spec.md names agreement, power and the three bias
    tolerances only)."""
    report = _report(
        pairwise_member_kappa=(("gpt#0", "claude#1", 0.1),),
        abstention_rate=0.9,
        member_families=("gpt", "claude"),
    )
    assert report.may_gate is True


def test_build_threads_panel_fields_through():
    canaries = [_canary("c1", "known_equal", "tie")]
    report = build_judge_calibration_report(
        "panel-1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=canaries,
        canary_verdicts=["tie"],
        pairwise_member_kappa=(("gpt#0", "claude#1", 0.42),),
        abstention_rate=0.05,
        member_families=("gpt", "claude"),
    )
    assert report.pairwise_member_kappa == (("gpt#0", "claude#1", 0.42),)
    assert report.abstention_rate == 0.05
    assert report.member_families == ("gpt", "claude")


def test_build_defaults_panel_fields_when_omitted():
    """A single-judge caller (every existing call site) doesn't need to know
    panel fields exist."""
    canaries = [_canary("c1", "known_equal", "tie")]
    report = build_judge_calibration_report(
        "j1",
        "art-1",
        n_total=10,
        n_codeterminate=10,
        percent_agreement=1.0,
        kappa=1.0,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=_passing_order(),
        verbosity=_passing_verbosity(),
        self_preference=None,
        canaries=canaries,
        canary_verdicts=["tie"],
    )
    assert report.pairwise_member_kappa == ()
    assert report.abstention_rate is None
    assert report.member_families == ()


def test_build_rejects_non_canary_item():
    plain = PairwiseItem(
        item_id="p", prompt="p", answer_a="a", answer_b="b", family_a="gpt", family_b="claude"
    )
    with pytest.raises(ValueError, match="not a canary"):
        build_judge_calibration_report(
            "j1",
            "art-1",
            n_total=1,
            n_codeterminate=1,
            percent_agreement=1.0,
            kappa=1.0,
            directional_only=False,
            agreement_may_gate=True,
            order_flip=_passing_order(),
            verbosity=_passing_verbosity(),
            self_preference=None,
            canaries=[plain],
            canary_verdicts=["a"],
        )
