"""Merge-time outcome seeding — closes the F-010 audit-data seam (ADR 0005).

Run as a module::

    python -m agent_core.merge_seed --store <jsonl> --change-id <id> \
        --domain <d> --raw-confidence <f> [--merged-at <iso>] [--agent-version <v>]

Why this exists
---------------
The calibrated merge gate (:mod:`agent_core.merge_gate_ci`) decides
MERGE / ESCALATE / REJECT but never persists anything the downstream labeller or
audit sampler can later resolve. Both
:func:`agent_core.outcome_labeller.label_matured` and
:func:`agent_core.audit_sampler.select_for_audit` / ``record_verdict`` iterate
``store.resolved()`` — they only ever act on records that ALREADY exist, and
``record_verdict`` raises ``KeyError`` for an unknown ``change_id``. So without an
initial *pending* record written at merge time, no domain accumulates
HUMAN_AUDIT history and every domain stays in cold-start ESCALATE forever
(:func:`agent_core.outcome_store.build_domain_models` then yields ``tau is None``).

This module writes that initial pending record (``label=None``). It is the only
seam ADR 0005 left open; detection (reverts / CI failures) was already wired.

Safety
------
Seeding is inert and default-off:

* A pending record changes **no** gate decision — the gate reads only
  HUMAN_AUDIT records, so a ``label=None`` row is invisible to ``tau`` and health.
* It is **idempotent** — a ``change_id`` already present in the store is never
  re-seeded, so re-running on the same merge (e.g. a workflow retry) is a no-op.
* Reuses :class:`agent_core.outcome_store.OutcomeStore` / ``OutcomeRecord``; it
  introduces no parallel store and no new record shape.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .logging_util import get_logger
from .outcome_store import OutcomeRecord, OutcomeStore

logger = get_logger(__name__)


def already_seeded(store: OutcomeStore, change_id: str) -> bool:
    """True if any record for ``change_id`` already exists in the store."""
    return any(r.change_id == change_id for r in store.all())


def seed_pending(
    store: OutcomeStore,
    change_id: str,
    domain: str,
    raw_confidence: float,
    merged_at: str | None = None,
    agent_version: str | None = None,
    now: datetime | None = None,
) -> OutcomeRecord | None:
    """Append the initial pending ``OutcomeRecord`` for a freshly merged change.

    Returns the new record, or ``None`` if ``change_id`` is already in the store
    (idempotent — safe to call repeatedly for the same merge). ``merged_at``
    defaults to ``now`` (UTC) when omitted; ``now`` is injectable for
    deterministic tests.
    """
    if already_seeded(store, change_id):
        return None
    if merged_at is None:
        merged_at = (now or datetime.now(timezone.utc)).isoformat()
    rec = OutcomeRecord(
        change_id=change_id,
        domain=domain,
        raw_confidence=raw_confidence,
        merged_at=merged_at,
        label=None,  # pending — the labeller / audit sampler resolve it later
        label_source=None,
        labeled_at=None,
        agent_version=agent_version,
    )
    store.append(rec)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed a pending merge-outcome record (F-010 audit-data seam)."
    )
    ap.add_argument("--store", required=True)
    ap.add_argument("--change-id", dest="change_id", required=True)
    ap.add_argument("--domain", required=True)
    ap.add_argument("--raw-confidence", dest="raw_confidence", type=float, required=True)
    ap.add_argument("--merged-at", dest="merged_at", help="ISO-8601 merge time (default: now UTC)")
    ap.add_argument(
        "--agent-version",
        dest="agent_version",
        help="optional impl+config keying hash for the flow-calibration corpus",
    )
    args = ap.parse_args(argv)

    store = OutcomeStore(args.store)
    rec = seed_pending(
        store,
        args.change_id,
        args.domain,
        args.raw_confidence,
        merged_at=args.merged_at,
        agent_version=args.agent_version,
    )
    if rec is None:
        logger.info("merge-seed already seeded change_id=%s (no-op)", args.change_id)
        print(f"already seeded: {args.change_id} (no-op)")
        return 0
    logger.info("merge-seed pending change_id=%s domain=%s", rec.change_id, rec.domain)
    print(
        f"seeded pending outcome {rec.change_id} "
        f"domain={rec.domain} raw_confidence={rec.raw_confidence}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
