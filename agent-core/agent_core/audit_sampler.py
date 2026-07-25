"""Audit sampler (active / authoritative signal).

Run as a module:  ``python -m agent_core.audit_sampler {select,record} --store <jsonl>``.

Selects a random sample of merged changes for human verification. Randomness is
the point: it produces an UNBIASED label set, the only sound basis for the
gate's risk guarantee. Stratified by domain so low-volume domains still
accumulate enough audits to leave cold start.

Two operations:
  select  -> choose change_ids to audit (Bernoulli rate, with a per-domain floor)
  record  -> ingest a human verdict as an authoritative HUMAN_AUDIT label
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from .logging_util import get_logger
from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore

logger = get_logger(__name__)


#: SIGNIFICANT FIGURES (not decimal places) used whenever a propensity is rendered. Single
#: point of truth: the issue body, the dispatch command it prints, and the recorder's log
#: must agree, or an operator copying one into the other silently changes the value.
PROPENSITY_SIGFIGS = 6

#: Rendered in place of a probability that was never captured.
PROPENSITY_UNKNOWN = "unknown"


def is_valid_propensity(value: float | None) -> bool:
    """``True`` when ``value`` is a usable inclusion probability, or ``None`` (unknown).

    The single definition of the contract. Every layer that touches a propensity checks
    against *this* predicate rather than restating the comparison, because the naive
    ``0.0 < value <= 1.0`` form silently admits nothing but also silently *depends* on
    NaN comparing false — an equivalence that is true by accident, not by design, and
    that a later edit could easily break in one copy but not the others.

    ``0`` is excluded, not merely out of range: a record sampled with probability zero is
    a contradiction, and its ``1 / p`` weight is undefined.
    """
    return value is None or (math.isfinite(value) and 0.0 < value <= 1.0)


def format_propensity(value: float | None, *, unknown: str = PROPENSITY_UNKNOWN) -> str:
    """Render a propensity, or ``unknown`` when it was never captured.

    Uses ``g`` (significant figures), **not** ``f`` (decimal places), because this output is
    not merely displayed — it is pasted into the ``gh workflow run`` command the audit issue
    prints, so it has to parse back to the *same* usable probability.

    Fixed-point rendering broke that: ``1e-7`` became ``"0.000000"``, which parses to ``0.0``
    and is rejected by :func:`is_valid_propensity`. A value the contract accepts would have
    produced a dispatch command guaranteed to fail at the recorder — the same failure mode
    the ingestion guard exists to prevent, reintroduced one layer later. ``g`` switches to an
    exponent instead of collapsing to zero, so ``format`` -> ``float`` preserves validity
    across the whole domain (pinned by a property test), and it is *tidier* for the
    arithmetic-noise values ``inclusion_probability`` actually emits: ``0.6`` not
    ``0.600000``.

    The round trip preserves *validity and value to the rendered precision*, not the exact
    bits: six significant figures costs ~1e-6 relative error, which is immaterial in a
    ``1 / p`` weight and buys a number a human can actually read (``0.2 + 0.4`` renders
    ``0.6``, not ``0.6000000000000001``).
    """
    return unknown if value is None else f"{value:.{PROPENSITY_SIGFIGS}g}"


@dataclass(frozen=True)
class AuditConfig:
    base_rate: float = 0.05  # audit ~5% of merges at random
    per_domain_floor: int = 30  # but guarantee >= this many audits per domain


@dataclass(frozen=True)
class AuditSelection:
    """One sampled change plus the probability with which it was sampled.

    ``propensity`` is the *marginal* inclusion probability for this record's
    domain-round. Every candidate in a domain shares it, because selection is
    content-blind: the pool is shuffled, the first ``need_floor`` are taken
    outright and the rest are Bernoulli(``base_rate``). It is recorded — never
    used to choose — so a later estimator can weight audits by ``1 / propensity``
    (Horvitz-Thompson / prediction-powered). That weight corrects the mild
    over-sampling the per-domain floor induces in low-volume domains, and it
    cannot be reconstructed once the round is over.
    """

    change_id: str
    domain: str
    propensity: float


def inclusion_probability(n_candidates: int, need_floor: int, base_rate: float) -> float:
    """Marginal ``P(selected)`` for one candidate in a domain-round.

    After the shuffle every candidate is equally likely to hold any position, so it is
    taken by the floor with probability ``floor_frac = min(1, need_floor / n_candidates)``
    and is otherwise sampled at ``base_rate``. The result is a convex combination of ``1``
    and ``base_rate``, hence always within ``[base_rate, 1]`` — never zero for a candidate
    that can actually be drawn, which is what keeps ``1 / propensity`` finite.

    Written as ``base_rate + floor_frac * (1 - base_rate)`` rather than the equivalent
    ``floor_frac + (1 - floor_frac) * base_rate``: the two agree algebraically, but only
    this ordering keeps ``result >= base_rate`` and ``result <= 1`` exact in floating
    point. The other form can round one ULP below ``base_rate`` for rates near 1.
    """
    if n_candidates <= 0:
        return 0.0
    floor_frac = min(1.0, max(0, need_floor) / n_candidates)
    return base_rate + floor_frac * (1.0 - base_rate)


def select_for_audit_detailed(
    store: OutcomeStore, cfg: AuditConfig, rng: random.Random | None = None
) -> list[AuditSelection]:
    """Select change_ids for human audit, each with its inclusion probability.

    Unbiased: selection ignores the change's content, confidence, and any passive
    label. Stratified by domain so low-volume domains still leave cold start.

    This is the full-information form of :func:`select_for_audit`; the two consume the
    RNG in exactly the same order, so for a given seed they pick exactly the same set.
    """
    rng = rng or random.SystemRandom()
    resolved = store.resolved()
    audited_per_domain: dict[str, int] = {}
    for r in resolved.values():
        if r.label_source == LabelSource.HUMAN_AUDIT.value:
            audited_per_domain[r.domain] = audited_per_domain.get(r.domain, 0) + 1

    # candidates = merged changes not yet audited
    candidates = [r for r in resolved.values() if r.label_source != LabelSource.HUMAN_AUDIT.value]
    by_domain: dict[str, list[OutcomeRecord]] = {}
    for r in candidates:
        by_domain.setdefault(r.domain, []).append(r)

    picked: list[AuditSelection] = []
    for domain, recs in by_domain.items():
        have = audited_per_domain.get(domain, 0)
        need_floor = max(0, cfg.per_domain_floor - have)
        propensity = inclusion_probability(len(recs), need_floor, cfg.base_rate)
        rng.shuffle(recs)
        # NOTE: `or` short-circuits, so rng.random() is consumed only past the floor.
        # Any refactor here must preserve that call order or seeded selection changes.
        picked_here = 0
        for i, r in enumerate(recs):
            if i < need_floor or rng.random() < cfg.base_rate:
                picked.append(AuditSelection(r.change_id, domain, propensity))
                picked_here += 1
        logger.debug(
            "audit selection: domain=%s candidates=%d audited=%d need_floor=%d "
            "propensity=%s picked=%d",
            domain,
            len(recs),
            have,
            need_floor,
            format_propensity(propensity),
            picked_here,
        )
    logger.info(
        "audit sampler selected %d change(s) across %d domain(s) (base_rate=%s, floor=%s)",
        len(picked),
        len(by_domain),
        cfg.base_rate,
        cfg.per_domain_floor,
    )
    return picked


def select_for_audit(
    store: OutcomeStore, cfg: AuditConfig, rng: random.Random | None = None
) -> list[str]:
    """Return change_ids to send for human audit. Unbiased: selection ignores
    the change's content, confidence, and any passive label.

    Backwards-compatible view of :func:`select_for_audit_detailed` — same selection,
    same RNG consumption, change_ids only.
    """
    return [s.change_id for s in select_for_audit_detailed(store, cfg, rng)]


def record_verdict(
    store: OutcomeStore,
    change_id: str,
    correct: bool,
    now: datetime | None = None,
    *,
    selection_propensity: float | None = None,
) -> OutcomeRecord:
    """Append an authoritative HUMAN_AUDIT label for ``change_id``.

    ``selection_propensity`` is the probability this change was sampled with (see
    :class:`AuditSelection`); pass it through from the selection step so the audit can
    later be reweighted. It is validated here rather than on ``OutcomeRecord`` because
    that record is a deliberately dumb, load-tolerant holder (ADR 0025) — this is the
    write boundary, and a propensity we cannot interpret must not enter the store.
    """
    if not is_valid_propensity(selection_propensity):
        raise ValueError(
            f"selection_propensity must be a finite number in (0, 1] (got {selection_propensity!r})"
        )
    now = now or datetime.now(timezone.utc)
    src = store.resolved().get(change_id)
    if src is None:
        raise KeyError(f"unknown change_id: {change_id}")
    rec = OutcomeRecord(
        change_id=change_id,
        domain=src.domain,
        raw_confidence=src.raw_confidence,
        merged_at=src.merged_at,
        label=correct,
        label_source=LabelSource.HUMAN_AUDIT.value,
        labeled_at=now.isoformat(),
        selection_propensity=selection_propensity,
    )
    store.append(rec)
    logger.info(
        "recorded HUMAN_AUDIT verdict for %s (domain=%s, correct=%s, propensity=%s)",
        change_id,
        rec.domain,
        correct,
        format_propensity(selection_propensity),
    )
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit sampler.")
    ap.add_argument("--store", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--base-rate", type=float, default=AuditConfig.base_rate)
    s.add_argument("--per-domain-floor", type=int, default=AuditConfig.per_domain_floor)
    s.add_argument(
        "--with-propensity",
        action="store_true",
        help="emit '<change_id>\\t<propensity>' instead of bare ids (default: bare ids, "
        "so existing consumers are unaffected)",
    )
    r = sub.add_parser("record")
    r.add_argument("--change-id", required=True)
    r.add_argument(
        "--selection-propensity",
        type=float,
        default=None,
        help="probability this change was sampled with, from `select --with-propensity`; "
        "omitted means unknown (historical records)",
    )
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--correct", dest="correct", action="store_true")
    g.add_argument("--incorrect", dest="correct", action="store_false")
    args = ap.parse_args(argv)

    store = OutcomeStore(args.store)
    if args.cmd == "select":
        picks = select_for_audit_detailed(store, AuditConfig(args.base_rate, args.per_domain_floor))
        for sel in picks:
            # Through the shared renderer, not a local format spec: this line IS the
            # serialisation boundary that audit_issue_sync reads back, so a hand-rolled
            # `.6f` here would let the producer emit values its own consumer rejects.
            print(
                f"{sel.change_id}\t{format_propensity(sel.propensity)}"
                if args.with_propensity
                else sel.change_id
            )
        print(f"# selected {len(picks)} for audit", file=sys.stderr)
    else:
        # An out-of-contract --selection-propensity is an operator error, not a bug:
        # surface it as a clean message + exit 2 (the repo's usage-error code) rather than
        # a raw traceback. An unknown --change-id keeps raising, unchanged: that means the
        # store does not hold the record, which is a real integrity problem, not a typo in
        # a flag.
        try:
            rec = record_verdict(
                store,
                args.change_id,
                args.correct,
                selection_propensity=args.selection_propensity,
            )
        except ValueError as exc:
            logger.error("audit-sampler: %s", exc)
            return 2
        print(f"recorded audit {rec.change_id} correct={rec.label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
