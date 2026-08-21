"""Judge bias calibration report: agreement, kappa and every bias probe, composed.

A separate module from :mod:`agent_core.calibration_report` (agent-records proxy
calibration — a different capability, ADR 0023) and from
:mod:`agent_core.judge_calibration` (the probe math itself) — this is the
composition layer that assembles one judge's full calibration picture.

``agent_core`` cannot compute Cohen's kappa against human labels itself:
:mod:`flow_corpus.oracles.kappa_gate` (which already implements indeterminate-pair
exclusion and power gating) sits *downstream* of ``agent_core`` in the dependency
graph (``architecture.yaml``: ``flow_corpus: [flow_protocol, agent_core]``), so an
``agent_core -> flow_corpus`` import would be a reverse edge. The agreement
fields on :class:`JudgeCalibrationReport` are therefore populated by the caller
(``behavioral_regression``, which already depends on both) from its own
``flow_corpus.oracles.kappa_gate.validate_oracle`` call — this module defines the
report's shape and its gating verdict, never how agreement was computed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .judge_calibration import OrderProbeResult, SelfPreferenceResult, VerbosityProbeResult
from .pairwise import PairwiseItem

#: Independent of agent_core.version.SCHEMA_VERSION (the framework config schema) —
#: this versions the report payload shape specifically, bumped only when that
#: shape changes (mirrors eval_harness's TRAJECTORY_SCHEMA_VERSION precedent).
#: 1.1.0 (add-panel-judge, F-059): additive-only — three new optional fields
#: (pairwise_member_kappa, abstention_rate, member_families) for panel-member
#: calibration; every pre-1.1.0 field is unchanged, so a 1.0.0-shaped construction
#: still round-trips (the new fields just default empty/None).
REPORT_SCHEMA_VERSION = "1.1.0"


def _canary_pass_rate(canaries: Sequence[PairwiseItem], verdicts: Sequence[str]) -> float:
    if not canaries:
        raise ValueError("build_judge_calibration_report: no canaries provided")
    if len(canaries) != len(verdicts):
        raise ValueError(
            "build_judge_calibration_report: canaries and verdicts must have equal length"
        )
    for c in canaries:
        if c.canary_kind is None:
            raise ValueError(f"build_judge_calibration_report: item {c.item_id!r} is not a canary")
    correct = sum(1 for c, v in zip(canaries, verdicts, strict=True) if v == c.expected)
    return correct / len(canaries)


@dataclass(frozen=True)
class JudgeCalibrationReport:
    """One judge's full bias calibration picture, versioned and self-describing.

    ``may_gate`` is the single verdict a gate decision reads; ``failing_checks``
    names which specific check(s) are responsible when it is ``False`` — spec.md's
    "the reason names the failing bias check" requirement. Canary results are
    diagnostic only (design.md: "detected rather than scoring a flattering kappa"),
    not part of ``may_gate`` — spec.md's ADDED Requirements name agreement, power
    and the three bias tolerances as the gating conditions, not canaries.
    """

    schema_version: str
    judge_id: str
    artifact_id: str
    n_total: int
    n_codeterminate: int
    percent_agreement: float
    kappa: float | None
    directional_only: bool
    agreement_may_gate: bool
    order_flip: OrderProbeResult
    verbosity: VerbosityProbeResult
    self_preference: SelfPreferenceResult | None
    canary_pass_rate: float
    #: Panel-only (F-059): empty/None for a single-judge report. Cohen's kappa
    #: between every pair of a PanelJudge's members' pass/fail calls across a
    #: calibration corpus — see eval_harness.agent_core_adapter.pairwise_member_kappa,
    #: which computes this; this dataclass only carries the already-computed result.
    pairwise_member_kappa: tuple[tuple[str, str, float], ...] = ()
    #: Panel-only (F-059): fraction of corpus items the panel abstained on
    #: (below quorum or over its disagreement threshold). None for a single judge,
    #: which has no abstention concept.
    abstention_rate: float | None = None
    #: Panel-only (F-059): each member's judge family (e.g. "gpt", "claude"),
    #: for spotting a panel that is diverse in name only (all members one family).
    member_families: tuple[str, ...] = ()

    @property
    def may_gate(self) -> bool:
        return self.agreement_may_gate and not self.failing_checks

    @property
    def failing_checks(self) -> tuple[str, ...]:
        """Names of the checks currently failing — empty when the report may gate."""
        failures: list[str] = []
        if not self.agreement_may_gate:
            failures.append("agreement_or_power")
        if not self.order_flip.passes:
            failures.append("order_flip")
        if not self.verbosity.passes:
            failures.append("verbosity")
        if self.self_preference is not None and not self.self_preference.passes:
            failures.append("self_preference")
        return tuple(failures)


def build_judge_calibration_report(
    judge_id: str,
    artifact_id: str,
    *,
    n_total: int,
    n_codeterminate: int,
    percent_agreement: float,
    kappa: float | None,
    directional_only: bool,
    agreement_may_gate: bool,
    order_flip: OrderProbeResult,
    verbosity: VerbosityProbeResult,
    self_preference: SelfPreferenceResult | None,
    canaries: Sequence[PairwiseItem],
    canary_verdicts: Sequence[str],
    pairwise_member_kappa: tuple[tuple[str, str, float], ...] = (),
    abstention_rate: float | None = None,
    member_families: tuple[str, ...] = (),
) -> JudgeCalibrationReport:
    """Assemble a :class:`JudgeCalibrationReport` from already-computed sub-results.

    Every bias-probe and agreement argument is expected to already be computed
    (via :mod:`agent_core.judge_calibration` and, for agreement, the caller's own
    ``flow_corpus`` call) — this function's only real work is the canary check,
    since ``PairwiseItem.expected`` and the judge's actual verdict on each canary
    aren't compared anywhere else. ``pairwise_member_kappa``/``abstention_rate``/
    ``member_families`` are panel-only (F-059); omit them for a single-judge report.
    """
    canary_rate = _canary_pass_rate(canaries, canary_verdicts)
    return JudgeCalibrationReport(
        schema_version=REPORT_SCHEMA_VERSION,
        judge_id=judge_id,
        artifact_id=artifact_id,
        n_total=n_total,
        n_codeterminate=n_codeterminate,
        percent_agreement=percent_agreement,
        kappa=kappa,
        directional_only=directional_only,
        agreement_may_gate=agreement_may_gate,
        order_flip=order_flip,
        verbosity=verbosity,
        self_preference=self_preference,
        canary_pass_rate=canary_rate,
        pairwise_member_kappa=pairwise_member_kappa,
        abstention_rate=abstention_rate,
        member_families=member_families,
    )
