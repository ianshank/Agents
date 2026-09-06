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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    if not is_dataclass(probe) or isinstance(probe, type):
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
        "self_preference": (
            _probe_to_dict(report.self_preference) if report.self_preference is not None else None
        ),
        "canary_pass_rate": report.canary_pass_rate,
        "pairwise_member_kappa": [list(row) for row in report.pairwise_member_kappa],
        "abstention_rate": report.abstention_rate,
        "member_families": list(report.member_families),
    }
    return payload


def _require_bool(value: object, name: str) -> bool:
    """Accept only JSON booleans (reject strings and 0/1 ints)."""
    if type(value) is not bool:
        raise TypeError(f"{name} must be a JSON boolean, got {type(value).__name__}: {value!r}")
    return value


def _require_int(value: object, name: str) -> int:
    """Accept only JSON integers (bool is a subclass of int — reject it)."""
    if type(value) is not int:
        raise TypeError(f"{name} must be a JSON integer, got {type(value).__name__}: {value!r}")
    return value


def _require_float(value: object, name: str) -> float:
    """Accept JSON numbers; reject bools and non-numeric types."""
    if type(value) is bool or type(value) not in (int, float):
        raise TypeError(f"{name} must be a JSON number, got {type(value).__name__}: {value!r}")
    return float(value)


def _require_str(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a JSON string, got {type(value).__name__}: {value!r}")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, name)


def _order_probe_from_dict(data: dict[str, Any]) -> OrderProbeResult:
    return OrderProbeResult(
        n=_require_int(data["n"], "order_flip.n"),
        flips=_require_int(data["flips"], "order_flip.flips"),
        flip_rate=_require_float(data["flip_rate"], "order_flip.flip_rate"),
        ci_low=_require_float(data["ci_low"], "order_flip.ci_low"),
        ci_high=_require_float(data["ci_high"], "order_flip.ci_high"),
        passes=_require_bool(data["passes"], "order_flip.passes"),
        degenerate=_optional_str(data.get("degenerate"), "order_flip.degenerate"),
    )


def _verbosity_probe_from_dict(data: dict[str, Any]) -> VerbosityProbeResult:
    return VerbosityProbeResult(
        n=_require_int(data["n"], "verbosity.n"),
        ties=_require_int(data["ties"], "verbosity.ties"),
        concise_wins=_require_int(data["concise_wins"], "verbosity.concise_wins"),
        expanded_wins=_require_int(data["expanded_wins"], "verbosity.expanded_wins"),
        expanded_win_rate=_require_float(data["expanded_win_rate"], "verbosity.expanded_win_rate"),
        preference_delta=_require_float(data["preference_delta"], "verbosity.preference_delta"),
        ci_low=_require_float(data["ci_low"], "verbosity.ci_low"),
        ci_high=_require_float(data["ci_high"], "verbosity.ci_high"),
        passes=_require_bool(data["passes"], "verbosity.passes"),
        degenerate=_optional_str(data.get("degenerate"), "verbosity.degenerate"),
    )


def _self_preference_from_dict(data: dict[str, Any]) -> SelfPreferenceResult:
    return SelfPreferenceResult(
        judge_family=_require_str(data["judge_family"], "self_preference.judge_family"),
        same_family_n=_require_int(data["same_family_n"], "self_preference.same_family_n"),
        same_family_win_rate=_require_float(
            data["same_family_win_rate"], "self_preference.same_family_win_rate"
        ),
        same_family_ci_low=_require_float(
            data["same_family_ci_low"], "self_preference.same_family_ci_low"
        ),
        same_family_ci_high=_require_float(
            data["same_family_ci_high"], "self_preference.same_family_ci_high"
        ),
        other_family_n=_require_int(data["other_family_n"], "self_preference.other_family_n"),
        other_family_win_rate=_require_float(
            data["other_family_win_rate"], "self_preference.other_family_win_rate"
        ),
        other_family_ci_low=_require_float(
            data["other_family_ci_low"], "self_preference.other_family_ci_low"
        ),
        other_family_ci_high=_require_float(
            data["other_family_ci_high"], "self_preference.other_family_ci_high"
        ),
        delta=_require_float(data["delta"], "self_preference.delta"),
        passes=_require_bool(data["passes"], "self_preference.passes"),
        degenerate=_optional_str(data.get("degenerate"), "self_preference.degenerate"),
    )


def judge_calibration_report_from_dict(data: dict[str, Any]) -> JudgeCalibrationReport:
    """Build a :class:`JudgeCalibrationReport` from :func:`judge_calibration_report_to_dict` output.

    Fail-closed: missing required keys or wrong types raise ``ValueError`` / ``TypeError``.
    JSON strings like ``"false"`` are never coerced to booleans.
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
    for key in ("n", "flips", "flip_rate", "ci_low", "ci_high", "passes"):
        if key not in order:
            raise ValueError(f"order_flip missing required key: {key!r}")
    for key in (
        "n",
        "ties",
        "concise_wins",
        "expanded_wins",
        "expanded_win_rate",
        "preference_delta",
        "ci_low",
        "ci_high",
        "passes",
    ):
        if key not in verbosity:
            raise ValueError(f"verbosity missing required key: {key!r}")

    self_pref_raw = data.get("self_preference")
    if self_pref_raw is None:
        self_pref = None
    elif isinstance(self_pref_raw, dict):
        self_pref = _self_preference_from_dict(self_pref_raw)
    else:
        raise TypeError(
            f"self_preference must be an object or null, got {type(self_pref_raw).__name__}"
        )

    pairwise_raw = data.get("pairwise_member_kappa") or ()
    if not isinstance(pairwise_raw, (list, tuple)):
        raise TypeError("pairwise_member_kappa must be an array")
    pairwise: tuple[tuple[str, str, float], ...] = tuple(
        (_require_str(a, "pairwise_member_kappa[0]"),
         _require_str(b, "pairwise_member_kappa[1]"),
         _require_float(k, "pairwise_member_kappa[2]"))
        for a, b, k in pairwise_raw
    )
    families_raw = data.get("member_families") or ()
    if not isinstance(families_raw, (list, tuple)):
        raise TypeError("member_families must be an array")
    families = tuple(_require_str(x, "member_families[]") for x in families_raw)

    kappa_raw = data.get("kappa")
    kappa = None if kappa_raw is None else _require_float(kappa_raw, "kappa")
    abstention_raw = data.get("abstention_rate")
    abstention = (
        None if abstention_raw is None
        else _require_float(abstention_raw, "abstention_rate")
    )

    return JudgeCalibrationReport(
        schema_version=_require_str(data["schema_version"], "schema_version"),
        judge_id=_require_str(data["judge_id"], "judge_id"),
        artifact_id=_require_str(data["artifact_id"], "artifact_id"),
        n_total=_require_int(data["n_total"], "n_total"),
        n_codeterminate=_require_int(data["n_codeterminate"], "n_codeterminate"),
        percent_agreement=_require_float(data["percent_agreement"], "percent_agreement"),
        kappa=kappa,
        directional_only=_require_bool(data["directional_only"], "directional_only"),
        agreement_may_gate=_require_bool(data["agreement_may_gate"], "agreement_may_gate"),
        order_flip=_order_probe_from_dict(order),
        verbosity=_verbosity_probe_from_dict(verbosity),
        self_preference=self_pref,
        canary_pass_rate=_require_float(data["canary_pass_rate"], "canary_pass_rate"),
        pairwise_member_kappa=pairwise,
        abstention_rate=abstention,
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
