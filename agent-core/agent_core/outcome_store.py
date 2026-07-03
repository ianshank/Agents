"""Outcome store + unbiased calibration builder for the merge gate.

Shared substrate for the labeller, the audit sampler, and the merge-gate CLI.

Authoritative-label rule: a change may accumulate several outcome records (a
passive revert signal, then a human audit). The HUMAN_AUDIT label always wins,
and the auto-merge guarantee (``tau``, health) is computed from HUMAN_AUDIT
records ONLY, because they are the unbiased random sample. Passive labels are
monitoring/alerting signals and never raise the auto-merge ceiling.

Calibration metrics are reused from :mod:`agent_core.calibration` (``auroc``,
``expected_calibration_error``, ``wilson_interval``); only the histogram
calibrator is local, since it is genuinely distinct from the isotonic one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from .calibration import auroc, expected_calibration_error, wilson_interval
from .jsonl import read_jsonl
from .logging_util import get_logger
from .merge_gate import CalibratorHealth, GatePolicyConfig, threshold_for_risk

logger = get_logger(__name__)


class LabelSource(str, Enum):
    REVERT = "revert"  # passive: a revert commit referenced this change
    CI_FAILURE = "ci_failure"  # passive: net-new failure attributed to this change
    TIMEOUT_CLEAN = "timeout_clean"  # passive: window elapsed, nothing observed
    HUMAN_AUDIT = "human_audit"  # active: randomly sampled, human-verified (authoritative)


@dataclass(frozen=True)
class OutcomeRecord:
    change_id: str
    domain: str
    raw_confidence: float
    merged_at: str  # ISO-8601
    label: bool | None = None  # True=correct, False=incorrect, None=pending
    label_source: str | None = None
    labeled_at: str | None = None
    # Optional keying axis for the flow-calibration corpus: hash(impl + agent_config).
    # Defaults to None so pre-1.3.0 JSONL lines (no field) still load via from_json.
    # The merge gate's per-domain models ignore this; corpus tooling groups by it.
    agent_version: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(line: str) -> OutcomeRecord:
        return OutcomeRecord(**json.loads(line))


class OutcomeStore:
    """Append-only JSONL store. Append-only keeps a tamper-evident audit trail."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, rec: OutcomeRecord) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(rec.to_json() + "\n")
        logger.debug(
            "appended outcome for %s (domain=%s, label_source=%s)",
            rec.change_id,
            rec.domain,
            rec.label_source,
        )

    def all(self) -> list[OutcomeRecord]:
        return read_jsonl(self.path, OutcomeRecord.from_json)

    def resolved(self) -> dict[str, OutcomeRecord]:
        """One authoritative record per change_id (HUMAN_AUDIT wins, else latest labeled)."""
        out: dict[str, OutcomeRecord] = {}
        for r in self.all():
            cur = out.get(r.change_id)
            if cur is None:
                out[r.change_id] = r
                continue
            if r.label_source == LabelSource.HUMAN_AUDIT.value:
                out[r.change_id] = r  # audit always wins
            elif cur.label_source != LabelSource.HUMAN_AUDIT.value and r.labeled_at:
                out[r.change_id] = r  # otherwise latest labeled
        return out


@dataclass(frozen=True)
class BinningCalibrator:
    """Histogram calibrator: predict = empirical accuracy of the score's bin."""

    edges: tuple[float, ...]
    bin_acc: tuple[float, ...]

    def predict(self, raw_score: float) -> float:
        return self.bin_acc[self.bin_index(raw_score)]

    def bin_index(self, raw_score: float) -> int:
        """Index of the score's bin. Distinct bins never conflate even when they
        share the same empirical accuracy (unlike grouping by ``predict``)."""
        for i in range(len(self.bin_acc)):
            if raw_score < self.edges[i + 1]:
                return i
        return len(self.bin_acc) - 1  # score >= top edge (e.g. exactly 1.0)

    @staticmethod
    def fit(scores: list[float], labels: list[bool], bins: int = 10) -> BinningCalibrator:
        edges = tuple(b / bins for b in range(bins + 1))
        acc: list[float] = []
        for b in range(bins):
            idx = [
                k
                for k, s in enumerate(scores)
                if s >= edges[b] and (s < edges[b + 1] or b == bins - 1)
            ]
            acc.append(sum(1 for k in idx if labels[k]) / len(idx) if idx else 0.0)
        return BinningCalibrator(edges=edges, bin_acc=tuple(acc))


def _upper_half_ci_width(
    scores: list[float], labels: list[bool], z: float, bins: int = 10
) -> float:
    """Widest Wilson CI among bins in the upper score half — the region where
    auto-merges actually happen, so the relevant thinness signal."""
    widest = 0.0
    for b in range(bins // 2, bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [k for k, s in enumerate(scores) if s >= lo and (s < hi or b == bins - 1)]
        if not idx:
            continue
        succ = sum(1 for k in idx if labels[k])
        low, high = wilson_interval(succ, len(idx), z)
        widest = max(widest, high - low)
    return widest


@dataclass(frozen=True)
class DomainModel:
    calibrator: BinningCalibrator
    health: CalibratorHealth
    tau: float | None


def _fold(change_id: str) -> int:
    """Deterministic 0/1 fold assignment (stable across runs, unlike hash())."""
    digest = hashlib.sha256(change_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % 2


def build_domain_models(store: OutcomeStore, cfg: GatePolicyConfig) -> dict[str, DomainModel]:
    """Build per-domain (calibrator, health, tau) from HUMAN_AUDIT records only.

    The calibrator is fit on one deterministic fold and health + ``tau`` are
    measured on the held-out fold, so the risk threshold is not overfit. Domains
    without enough audit data get an untrustworthy health and ``tau is None`` ->
    the gate escalates them. That is the correct cold-start behaviour: autonomy
    is earned per domain as unbiased audit labels accumulate.
    """
    by_domain: dict[str, list[OutcomeRecord]] = {}
    for r in store.resolved().values():
        if r.label_source == LabelSource.HUMAN_AUDIT.value and r.label is not None:
            by_domain.setdefault(r.domain, []).append(r)

    models: dict[str, DomainModel] = {}
    for domain, recs in by_domain.items():
        fit_recs = [r for r in recs if _fold(r.change_id) == 0] or recs
        eval_recs = [r for r in recs if _fold(r.change_id) == 1] or recs

        cal = BinningCalibrator.fit(
            [r.raw_confidence for r in fit_recs], [bool(r.label) for r in fit_recs]
        )
        ev_raw = [r.raw_confidence for r in eval_recs]
        ev_labels = [bool(r.label) for r in eval_recs]
        ev_cal = [cal.predict(s) for s in ev_raw]
        ev_outcomes = [int(b) for b in ev_labels]

        # AUROC is undefined with a single class; treat it as no resolution (0.5),
        # which fails the health floor and keeps the domain in cold-start ESCALATE.
        both_classes = 0 in ev_outcomes and 1 in ev_outcomes
        ev_auroc = auroc(ev_raw, ev_outcomes) if both_classes else 0.5

        health = CalibratorHealth(
            n=len(recs),
            ece=expected_calibration_error(ev_cal, ev_outcomes),
            auroc=ev_auroc,
            # Bin by RAW (continuous) scores, not the discrete calibrated values,
            # so equal-accuracy bins aren't conflated into an over-narrow CI.
            bin_ci_width=_upper_half_ci_width(ev_raw, ev_labels, cfg.wilson_z),
        )
        tau = threshold_for_risk(ev_cal, ev_labels, cfg) if health.is_trustworthy(cfg) else None
        models[domain] = DomainModel(calibrator=cal, health=health, tau=tau)
    return models
