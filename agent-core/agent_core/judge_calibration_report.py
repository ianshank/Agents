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

import json
from pathlib import Path
from typing import Any

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


def _probe_to_dict(probe: object) -> dict[str, Any]:
    """Serialize a frozen probe dataclass to a plain dict (field order stable)."""
    from dataclasses import asdict, is_dataclass

    if probe is None:
        return None  # type: ignore[return-value]
    if not is_dataclass(probe):
        raise TypeError(f"probe must be a dataclass instance, got {type(probe)!r}")
    return asdict(probe)


def judge_calibration_report_to_dict(report: JudgeCalibrationReport) -> dict[str, Any]:
    """Round-tripable dict form of *report* (JSON-serializable)."""
    payload: dict[str, Any] = {
        "schema_version": report.schema_version,
        "judge_id": report.judge_id,
        "artifact_id": report.artifact_id,
        "n_total": report.n_total,
        "n_codeterminate": report.n_codeterminate,
        "percent_agreement": report.percent_agreement,
        "kappa": report.kappa,
        "directional_only": report.directional_only,
        "agreement_may_gate": report.agreement_may_gate,
        "order_flip": _probe_to_dict(report.order_flip),
        "verbosity": _probe_to_dict(report.verbosity),
        "self_preference": _probe_to_dict(report.self_preference) if report.self_preference is not None else None,
        "canary_pass_rate": report.canary_pass_rate,
        "pairwise_member_kappa": [list(row) for row in report.pairwise_member_kappa],
        "abstention_rate": report.abstention_rate,
        "member_families": list(report.member_families),
    }
    return payload


def judge_calibration_report_from_dict(data: dict[str, Any]) -> JudgeCalibrationReport:
    """Build a :class:`JudgeCalibrationReport` from :func:`judge_calibration_report_to_dict` output.

    Fail-closed: missing required keys or wrong types raise ``ValueError`` / ``TypeError``.
    """
    if not isinstance(data, dict):
        raise TypeError(f"calibration report payload must be a dict, got {type(data)!r}")
    required = (
        "schema_version",
        "judge_id",
        "artifact_id",
        "n_total",
        "n_codeterminate",
        "percent_agreement",
        "directional_only",
        "agreement_may_gate",
        "order_flip",
        "verbosity",
        "canary_pass_rate",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"calibration report missing required keys: {missing}")

    order = data["order_flip"]
    verbosity = data["verbosity"]
    if not isinstance(order, dict) or not isinstance(verbosity, dict):
        raise TypeError("order_flip and verbosity must be objects")

    self_pref_raw = data.get("self_preference")
    self_pref = SelfPreferenceResult(**self_pref_raw) if isinstance(self_pref_raw, dict) else None

    pairwise_raw = data.get("pairwise_member_kappa") or ()
    pairwise: tuple[tuple[str, str, float], ...] = tuple(
        (str(a), str(b), float(k)) for a, b, k in pairwise_raw
    )
    families_raw = data.get("member_families") or ()
    families = tuple(str(x) for x in families_raw)

    return JudgeCalibrationReport(
        schema_version=str(data["schema_version"]),
        judge_id=str(data["judge_id"]),
        artifact_id=str(data["artifact_id"]),
        n_total=int(data["n_total"]),
        n_codeterminate=int(data["n_codeterminate"]),
        percent_agreement=float(data["percent_agreement"]),
        kappa=(None if data.get("kappa") is None else float(data["kappa"])),
        directional_only=bool(data["directional_only"]),
        agreement_may_gate=bool(data["agreement_may_gate"]),
        order_flip=OrderProbeResult(**order),
        verbosity=VerbosityProbeResult(**verbosity),
        self_preference=self_pref,
        canary_pass_rate=float(data["canary_pass_rate"]),
        pairwise_member_kappa=pairwise,
        abstention_rate=(
            None if data.get("abstention_rate") is None else float(data["abstention_rate"])
        ),
        member_families=families,
    )


def load_judge_calibration_report(path: str | Path) -> JudgeCalibrationReport:
    """Load a report from a JSON file. Fail-closed on missing/unreadable/invalid payloads."""
    report_path = Path(path)
    if not report_path.is_file():
        raise FileNotFoundError(f"calibration report not found: {report_path}")
    try:
        raw = report_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read calibration report {report_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"calibration report root must be an object: {report_path}")
    return judge_calibration_report_from_dict(data)


def dump_judge_calibration_report(report: JudgeCalibrationReport, path: str | Path) -> None:
    """Write *report* as JSON (UTF-8, trailing newline). Parent dirs must exist."""
    report_path = Path(path)
    payload = judge_calibration_report_to_dict(report)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
