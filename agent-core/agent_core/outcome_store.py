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
import math
from dataclasses import asdict, dataclass, fields
from enum import Enum
from pathlib import Path

from .calibration import DEFAULT_N_BINS, auroc, expected_calibration_error, wilson_interval
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
    # Marginal probability with which the audit sampler selected this change, when known.
    # Defaults to None so records written before the field existed -- and every passively
    # labelled or pending record, which was never sampled -- still load unchanged.
    # Nothing in the gate reads it: it exists so a later estimator can weight audits by
    # 1/p (Horvitz-Thompson / prediction-powered), which is impossible to reconstruct after
    # the fact. Validation lives at the write boundary (``audit_sampler.record_verdict``),
    # not here, because this record is a deliberately dumb, load-tolerant holder (ADR 0025).
    selection_propensity: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @staticmethod
    def from_json(line: str) -> OutcomeRecord:
        """Parse one store line, tolerating fields a newer writer added (ADR 0025).

        Corruption still raises: malformed JSON, a non-object payload, a missing required
        field, or a wrong type all propagate, because an append-only audit store with a
        corrupt line has already lost its integrity guarantee and hiding that would be
        worse. An *unknown extra* field is a different thing — it is additive schema
        evolution, and `OutcomeRecord(**payload)` could not tell the two apart, since both
        raise ``TypeError``. Since ``store_sync`` deliberately preserves such a line
        verbatim so a pull/push never rewrites history it does not own, this reader used to
        be guaranteed to meet a record it would crash on during any rolling upgrade.

        Unknown fields are dropped from the in-memory record and logged, never written
        back: ``store_sync`` remains the writer and still round-trips the original line.
        """
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"outcome record must be a JSON object, got {type(payload).__name__}")
        known = {f.name for f in fields(OutcomeRecord)}
        unknown = sorted(set(payload) - known)
        if unknown:
            logger.warning(
                "outcome record %s carries unknown field(s) %s -- ignoring them; a newer "
                "writer is active against this reader (store_sync preserves the line as-is)",
                payload.get("change_id", "<no change_id>"),
                ", ".join(unknown),
            )
            payload = {k: v for k, v in payload.items() if k in known}
        return OutcomeRecord(**payload)


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


def _bin_of(raw_score: float, bins: int) -> int:
    """Single source of truth for score -> bin routing.

    Out-of-contract scores (non-finite, or outside ``[0, 1]``) floor to bin 0. Scores are
    *loaded*, not computed: ``OutcomeRecord`` is a deliberately dumb, load-tolerant holder
    (ADR 0025) whose validation lives at the write boundary, so this layer fails **closed**
    -- a score we cannot interpret is treated as no confidence, never as maximum confidence
    -- and never raises, because one malformed historical line must not fail the gate on
    every PR. ``agent_core.calibration`` raises on the same input, correctly: its inputs are
    computed by this module, so an out-of-range probability there is a bug, not bad data.

    Routing was previously written out three times with two different out-of-range policies:
    ``fit`` swept anything above 1.0 into the *top* bin and silently dropped anything below
    0.0, while ``bin_index`` floored both to bin 0. A fitted table could therefore hold a top
    -bin accuracy inflated by a score that ``bin_index`` would never route a query to.

    The edge-comparison scan is deliberate -- ``min(int(raw * bins), bins - 1)`` is NOT
    equivalent. ``0.7 * 10 == 6.999999999999999`` would route 0.7 to bin 6, whereas the scan
    matches the ``b / bins`` edges the calibrator actually stores.
    """
    if not math.isfinite(raw_score) or not 0.0 <= raw_score <= 1.0:
        return 0
    for i in range(bins):
        if raw_score < (i + 1) / bins:
            return i
    return bins - 1  # score >= top edge (e.g. exactly 1.0)


@dataclass(frozen=True)
class BinningCalibrator:
    """Histogram calibrator: predict = empirical accuracy of the score's bin."""

    edges: tuple[float, ...]
    bin_acc: tuple[float, ...]

    def predict(self, raw_score: float) -> float:
        return self.bin_acc[self.bin_index(raw_score)]

    def bin_index(self, raw_score: float) -> int:
        """Index of the score's bin. Distinct bins never conflate even when they
        share the same empirical accuracy (unlike grouping by ``predict``).

        Any score outside the ``[0, 1]`` contract -- including ``NaN`` and ``±inf`` -- is
        floored to bin 0 rather than left to fall through the scan. ``NaN < edge`` is False
        for every edge and ``inf`` exceeds them all, so both reached the ``score >= top
        edge`` return and were scored as the *highest*-confidence bucket; anything above
        1.0 did the same. Records reach this method straight from the store, where
        ``OutcomeRecord`` applies no validation and ``ChangeContext``'s check is bypassed,
        so the fail-closed choice is made here too: a score we cannot interpret is treated
        as no confidence, never as maximum confidence. ``1.0`` exactly is in contract and
        still lands in the top bin.

        Routing itself is delegated to :func:`_bin_of` so this method and ``fit`` cannot
        disagree about where a score belongs; only the per-query log line lives here.
        """
        if not math.isfinite(raw_score) or not 0.0 <= raw_score <= 1.0:
            logger.warning(
                "out-of-contract raw_score %r in bin_index; scoring as bin 0 (fail-closed)",
                raw_score,
            )
        return _bin_of(raw_score, len(self.bin_acc))

    @staticmethod
    def fit(
        scores: list[float], labels: list[bool], bins: int = DEFAULT_N_BINS
    ) -> BinningCalibrator:
        bad = sum(1 for s in scores if not (math.isfinite(s) and 0.0 <= s <= 1.0))
        if bad:
            # Aggregate, not per-record: one line per fit, however dirty the store is.
            logger.warning(
                "BinningCalibrator.fit: %d of %d score(s) outside the [0, 1] contract; "
                "binned as bin 0 (fail-closed, matching bin_index)",
                bad,
                len(scores),
            )
        edges = tuple(b / bins for b in range(bins + 1))
        acc: list[float] = []
        for b in range(bins):
            idx = [k for k, s in enumerate(scores) if _bin_of(s, bins) == b]
            acc.append(sum(1 for k in idx if labels[k]) / len(idx) if idx else 0.0)
        return BinningCalibrator(edges=edges, bin_acc=tuple(acc))


def _operating_bin_ci_width(
    scores: list[float], labels: list[bool], cfg: GatePolicyConfig
) -> float | None:
    """Widest Wilson CI among the bins that could plausibly reach AUTO_MERGE.

    Returns ``None`` when no bin qualifies -- the region is unmeasurable, not perfect.

    ``decide`` compares the CALIBRATED ``p`` against ``tau`` and then requires the operating
    bin's Wilson LOWER bound to clear ``wilson_floor``. So a bin whose Wilson UPPER bound
    cannot even reach that floor can never be an operating point, whatever ``tau`` turns out
    to be -- and ``tau`` is not knowable here, since it is derived *from* health. The floor,
    not ``tau``, therefore defines the region, and it defines it on the calibrator's own
    bins: the axis the decision is actually made on.

    This replaces a scan of the upper half of the *raw* score range, which was wrong twice
    over. It measured the wrong axis -- a domain whose audits all sit below raw 0.5 can
    still calibrate to ``p == 1.0`` and auto-merge, in a region that scan could not inspect,
    so its docstring's claim to cover "where auto-merges actually happen" was false. And it
    accumulated into a ``0.0`` initialiser, so an EMPTY region reduced to the identity of
    ``max`` and read as a perfectly tight one, vacuously satisfying ``max_bin_ci_width``:
    the one health floor that did no work while reporting a pass. No evidence is not
    evidence of no risk, so it is now ``None`` and ``is_trustworthy`` rejects it.

    Grouping is by bin INDEX, never by predicted value: two distinct bins can share an
    accuracy, and collapsing them would pool their counts into an over-narrow interval --
    a fail-open of exactly the kind being removed.

    Note this makes ``wilson_floor`` influence health: lowering it (weakening the
    per-decision check) admits more bins into the region and so makes health stricter. The
    two knobs balance rather than compound.
    """
    widest: float | None = None
    for b in range(cfg.n_bins):
        idx = [k for k, s in enumerate(scores) if _bin_of(s, cfg.n_bins) == b]
        if not idx:
            continue
        succ = sum(1 for k in idx if labels[k])
        low, high = wilson_interval(succ, len(idx), cfg.wilson_z)
        if high < cfg.wilson_floor:
            continue  # confidently below the per-decision floor: never an operating point
        width = high - low
        widest = width if widest is None else max(widest, width)
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
    # Everything that is not an authoritative, labelled audit record is excluded from the
    # fit. That exclusion is correct but invisible: an all-passive store yields no models
    # and therefore no tau, which is indistinguishable from "no records at all" unless we
    # say so. Tally the reasons and report them.
    excluded: dict[str, int] = {}
    for r in store.resolved().values():
        if r.label_source == LabelSource.HUMAN_AUDIT.value and r.label is not None:
            by_domain.setdefault(r.domain, []).append(r)
        else:
            reason = "unlabelled" if r.label is None else f"passive:{r.label_source}"
            excluded[reason] = excluded.get(reason, 0) + 1

    if excluded:
        logger.info(
            "build_domain_models: fitting on %d HUMAN_AUDIT record(s) across %d domain(s); "
            "excluded %d record(s) ineligible for the fit (%s)",
            sum(len(v) for v in by_domain.values()),
            len(by_domain),
            sum(excluded.values()),
            ", ".join(f"{k}={v}" for k, v in sorted(excluded.items())),
        )
    if not by_domain:
        logger.warning(
            "build_domain_models: no HUMAN_AUDIT records available -- every domain stays "
            "cold-start (tau=None) regardless of how many passive labels exist"
        )

    models: dict[str, DomainModel] = {}
    for domain, recs in by_domain.items():
        fit_recs = [r for r in recs if _fold(r.change_id) == 0] or recs
        eval_recs = [r for r in recs if _fold(r.change_id) == 1] or recs

        cal = BinningCalibrator.fit(
            [r.raw_confidence for r in fit_recs],
            [bool(r.label) for r in fit_recs],
            cfg.n_bins,
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
            ece=expected_calibration_error(ev_cal, ev_outcomes, cfg.n_bins),
            auroc=ev_auroc,
            # Group by RAW-score bin INDEX, not by the discrete calibrated value, so
            # equal-accuracy bins aren't conflated into an over-narrow CI. Which bins
            # count is decided on the decision axis (see _operating_bin_ci_width).
            bin_ci_width=_operating_bin_ci_width(ev_raw, ev_labels, cfg),
        )
        tau = threshold_for_risk(ev_cal, ev_labels, cfg) if health.is_trustworthy(cfg) else None
        models[domain] = DomainModel(calibrator=cal, health=health, tau=tau)
    return models
