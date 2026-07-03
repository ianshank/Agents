#!/usr/bin/env python3
"""Record a human audit verdict into the outcome store (F-034 wrapper).

The ONLY automated writer of the authoritative HUMAN_AUDIT label, invoked by the
human-triggered ``merge-gate-verdict`` workflow_dispatch. The TCB's
``audit_sampler.record_verdict`` appends unconditionally (I-2: sampler semantics
stay untouched), so this wrapper provides what the surface needs:

  * idempotency  — a change that already carries a HUMAN_AUDIT label is a logged
                   no-op, never a duplicate authoritative record
  * input safety — ``change_id`` must look like a merge SHA (rejects
                   injection-shaped dispatch input)
  * attribution  — the acting human (``--actor`` / ``$GITHUB_ACTOR``) is logged;
                   the store push adds the same actor to the data-branch commit

Exit codes:
    0 - verdict recorded, or already-audited no-op
    2 - configuration error (malformed change_id)
    3 - unknown change_id (fails loudly: a typo'd dispatch must not look green)
    1 - unexpected internal error
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections.abc import Sequence

from _cli import configure_logging
from agent_core.audit_sampler import record_verdict
from agent_core.outcome_store import LabelSource, OutcomeStore

logger = logging.getLogger(__name__)

# change_id is a merge-commit SHA (ADR 0018 §5); anything else is rejected
# before it reaches a subprocess-adjacent surface.
CHANGE_ID_RE = re.compile(r"^[0-9a-f]{7,40}$")
DEFAULT_ACTOR_ENV = "GITHUB_ACTOR"

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_CONFIG = 2
EXIT_UNKNOWN_CHANGE = 3


def resolve_actor(cli_actor: str | None) -> str:
    return cli_actor or os.environ.get(DEFAULT_ACTOR_ENV) or "unknown"


def record(store_path: str, change_id: str, correct: bool, actor: str) -> int:
    """Pre-checked, idempotent verdict recording. See module docstring."""
    if not CHANGE_ID_RE.match(change_id):
        logger.error("record-verdict: change_id %r is not a commit SHA", change_id)
        return EXIT_CONFIG
    store = OutcomeStore(store_path)
    current = store.resolved().get(change_id)
    if current is None:
        logger.error(
            "record-verdict: unknown change_id %s (store has no record; actor=%s)",
            change_id,
            actor,
        )
        return EXIT_UNKNOWN_CHANGE
    if current.label_source == LabelSource.HUMAN_AUDIT.value:
        logger.info(
            "record-verdict no-op: change_id=%s already human-audited (label=%s); re-dispatch by actor=%s ignored",
            change_id,
            current.label,
            actor,
        )
        return EXIT_OK
    rec = record_verdict(store, change_id, correct)
    logger.info(
        "record-verdict: change_id=%s correct=%s domain=%s actor=%s",
        rec.change_id,
        rec.label,
        rec.domain,
        actor,
    )
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record a human merge-gate audit verdict.")
    ap.add_argument("--store", required=True)
    ap.add_argument("--change-id", required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--correct", dest="correct", action="store_true")
    group.add_argument("--incorrect", dest="correct", action="store_false")
    ap.add_argument("--actor", help=f"acting human (default ${DEFAULT_ACTOR_ENV})")
    args = ap.parse_args(argv)

    configure_logging()
    try:
        return record(args.store, args.change_id, args.correct, resolve_actor(args.actor))
    except Exception as exc:  # unexpected -> exit 1, never silently pass
        print(f"record-verdict internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
