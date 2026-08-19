"""Oracle validation: measure the judge before it gates a launch.

An unvalidated judge is *advisory, not a gate*. We measure the judge's verdicts against
a human-label set via Cohen's κ and a statistical-power floor, reusing
``flow_corpus.oracles.kappa_gate.validate_oracle`` (which excludes indeterminate pairs
and power-gates via ``is_directional_only``). The judge may gate only when it both
clears ``min_judge_kappa`` and has enough co-determinate pairs to be non-directional.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_core import (
    JudgeCalibrationReport,
    OrderProbeResult,
    PairwiseItem,
    SelfPreferenceResult,
    VerbosityProbeResult,
)
from agent_core import build_judge_calibration_report as _build_calibration_report
from agent_core.golden import percent_agreement
from flow_corpus.oracles.kappa_gate import KappaReport, validate_oracle

from .config import BRConfig
from .judge import JVerdict


def validate_judge(
    verdicts: Sequence[JVerdict],
    human_labels: Sequence[bool | None],
    cfg: BRConfig,
) -> KappaReport:
    """Validate the judge's verdicts against an aligned human-label set.

    Indeterminate verdicts/labels (``None``) are dropped before κ is computed; below
    ``power_min_sample`` co-determinate pairs the result is directional-only and cannot
    gate. Returns a :class:`KappaReport` whose ``may_gate`` is the trust signal the
    detector and gate consume.
    """
    if len(verdicts) != len(human_labels):
        raise ValueError("verdicts and human_labels must be aligned (equal length)")
    judge_verdicts: list[bool | None] = [v.label for v in verdicts]
    return validate_oracle(judge_verdicts, list(human_labels), cfg.as_corpus_config())


def build_judge_calibration_report(
    judge_id: str,
    artifact_id: str,
    verdicts: Sequence[JVerdict],
    human_labels: Sequence[bool | None],
    cfg: BRConfig,
    *,
    order_flip: OrderProbeResult,
    verbosity: VerbosityProbeResult,
    self_preference: SelfPreferenceResult | None,
    canaries: Sequence[PairwiseItem],
    canary_verdicts: Sequence[str],
) -> JudgeCalibrationReport:
    """Compose this module's own agreement measurement with pre-computed bias
    probes into a full :class:`JudgeCalibrationReport` (extend-judge-calibration,
    Group 4 — "Wire into behavioral_regression alongside validate_judge").

    Reuses :func:`validate_judge` for the human-agreement half (κ, power,
    codeterminate count) and ``agent_core.golden.percent_agreement`` over the same
    codeterminate pairs for the raw agreement rate — never re-deriving either.
    The three bias probes (order-flip, verbosity, self-preference) come from a
    separate pairwise, order-swapped corpus this function does not itself run; they
    are accepted pre-computed, exactly like
    ``agent_core.judge_calibration_report.build_judge_calibration_report``'s own
    contract (see that module's docstring for why ``agent_core`` cannot compute
    agreement itself — the reverse-edge/airgap finding from Group 3).
    """
    if len(verdicts) != len(human_labels):
        raise ValueError("verdicts and human_labels must be aligned (equal length)")
    kappa_report = validate_judge(verdicts, human_labels, cfg)

    codeterminate = [
        (int(v.label), int(h))
        for v, h in zip(verdicts, human_labels, strict=True)
        if v.label is not None and h is not None
    ]
    judge_ints = [j for j, _ in codeterminate]
    human_ints = [h for _, h in codeterminate]
    agreement = percent_agreement(judge_ints, human_ints) if codeterminate else 0.0

    return _build_calibration_report(
        judge_id,
        artifact_id,
        n_total=kappa_report.n_total,
        n_codeterminate=kappa_report.n_codeterminate,
        percent_agreement=agreement,
        kappa=kappa_report.kappa,
        directional_only=kappa_report.directional_only,
        agreement_may_gate=kappa_report.may_gate,
        order_flip=order_flip,
        verbosity=verbosity,
        self_preference=self_preference,
        canaries=canaries,
        canary_verdicts=canary_verdicts,
    )
