"""Outcome labeller (passive / monitoring signals).

Run as a module:  ``python -m agent_core.outcome_labeller --store <jsonl>``.

Assigns labels to merged changes whose maturity window has elapsed, from
mechanically-observable signals only:
  * a revert commit referencing the change   -> incorrect (REVERT)
  * a net-new failure attributed to it        -> incorrect (CI_FAILURE)
  * neither, after the window closes          -> correct  (TIMEOUT_CLEAN, WEAK)

These labels drive alerting and fast rollback. They DO NOT underwrite the
auto-merge guarantee — TIMEOUT_CLEAN cannot see silent errors, so it is biased
optimistic. Only HUMAN_AUDIT labels (from audit_sampler) feed the gate's tau.
Detectors are Protocols: swap in git/GitHub/Datadog implementations.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore


@runtime_checkable
class RevertDetector(Protocol):
    def was_reverted(self, change_id: str, since: datetime) -> bool: ...


@runtime_checkable
class FailureAttributor(Protocol):
    def caused_failure(self, change_id: str, since: datetime) -> bool: ...


@dataclass(frozen=True)
class LabellerConfig:
    maturity_days: int = 7  # window after merge before TIMEOUT_CLEAN may be assigned


def _now() -> datetime:
    return datetime.now(timezone.utc)


def label_matured(
    store: OutcomeStore,
    reverts: RevertDetector,
    failures: FailureAttributor,
    cfg: LabellerConfig,
    now: datetime | None = None,
) -> list[OutcomeRecord]:
    """Emit passive labels for unlabelled, matured changes. Returns new records."""
    now = now or _now()
    resolved = store.resolved()
    emitted: list[OutcomeRecord] = []
    for change_id, rec in resolved.items():
        if rec.label is not None:
            continue  # already labelled
        merged = datetime.fromisoformat(rec.merged_at)
        if reverts.was_reverted(change_id, merged):
            src, lbl = LabelSource.REVERT, False
        elif failures.caused_failure(change_id, merged):
            src, lbl = LabelSource.CI_FAILURE, False
        elif now - merged >= timedelta(days=cfg.maturity_days):
            src, lbl = LabelSource.TIMEOUT_CLEAN, True  # WEAK positive
        else:
            continue  # not matured yet
        new = OutcomeRecord(
            change_id=change_id,
            domain=rec.domain,
            raw_confidence=rec.raw_confidence,
            merged_at=rec.merged_at,
            label=lbl,
            label_source=src.value,
            labeled_at=now.isoformat(),
        )
        store.append(new)
        emitted.append(new)
    return emitted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Passive outcome labeller.")
    ap.add_argument("--store", required=True)
    ap.add_argument("--maturity-days", type=int, default=LabellerConfig.maturity_days)
    args = ap.parse_args(argv)

    # Placeholder detectors: real deployments inject git/GitHub/Datadog clients.
    class _NoReverts:
        def was_reverted(self, change_id: str, since: datetime) -> bool:
            return False

    class _NoFailures:
        def caused_failure(self, change_id: str, since: datetime) -> bool:
            return False

    store = OutcomeStore(args.store)
    emitted = label_matured(
        store, _NoReverts(), _NoFailures(), LabellerConfig(maturity_days=args.maturity_days)
    )
    for r in emitted:
        print(f"labelled {r.change_id} {r.label_source} correct={r.label}")
    print(f"total new labels: {len(emitted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
