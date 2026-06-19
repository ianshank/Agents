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
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore


@dataclass(frozen=True)
class AuditConfig:
    base_rate: float = 0.05  # audit ~5% of merges at random
    per_domain_floor: int = 30  # but guarantee >= this many audits per domain


def select_for_audit(
    store: OutcomeStore, cfg: AuditConfig, rng: random.Random | None = None
) -> list[str]:
    """Return change_ids to send for human audit. Unbiased: selection ignores
    the change's content, confidence, and any passive label."""
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

    picked: list[str] = []
    for domain, recs in by_domain.items():
        have = audited_per_domain.get(domain, 0)
        need_floor = max(0, cfg.per_domain_floor - have)
        rng.shuffle(recs)
        for i, r in enumerate(recs):
            if i < need_floor or rng.random() < cfg.base_rate:
                picked.append(r.change_id)
    return picked


def record_verdict(
    store: OutcomeStore, change_id: str, correct: bool, now: datetime | None = None
) -> OutcomeRecord:
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
    )
    store.append(rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit sampler.")
    ap.add_argument("--store", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--base-rate", type=float, default=AuditConfig.base_rate)
    s.add_argument("--per-domain-floor", type=int, default=AuditConfig.per_domain_floor)
    r = sub.add_parser("record")
    r.add_argument("--change-id", required=True)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--correct", dest="correct", action="store_true")
    g.add_argument("--incorrect", dest="correct", action="store_false")
    args = ap.parse_args(argv)

    store = OutcomeStore(args.store)
    if args.cmd == "select":
        ids = select_for_audit(store, AuditConfig(args.base_rate, args.per_domain_floor))
        for cid in ids:
            print(cid)
        print(f"# selected {len(ids)} for audit", file=sys.stderr)
    else:
        rec = record_verdict(store, args.change_id, args.correct)
        print(f"recorded audit {rec.change_id} correct={rec.label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
