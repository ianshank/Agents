"""Local outcome-store file I/O and per-domain statistics (no git).

An absent store file is an empty store, never an error. Writes are atomic
(tmp + ``os.replace``) so a crashed run can never leave a half-written store.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ..atomic_io import atomic_write_text
from ..audit_sampler import AuditConfig
from ..outcome_store import LabelSource, OutcomeRecord
from .serialization import _split_lines, serialize_store

# Reserved stats key for lines this reader could not parse (observability —
# real domains come from config/merge-gate-domains.yaml and never start with _).
UNPARSED_STATS_KEY = "_unparsed"


def read_store_lines(path: str | Path) -> tuple[list[OutcomeRecord], list[str]]:
    """(records, opaque lines) of the local store; absent file is empty."""
    target = Path(path)
    if not target.exists():
        return [], []
    return _split_lines(target.read_text(encoding="utf-8"))


def read_store(path: str | Path) -> list[OutcomeRecord]:
    """Parsed records in the local store; an absent file is an empty store."""
    return read_store_lines(path)[0]


def write_store(
    path: str | Path, records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()
) -> None:
    """Atomically replace the local store with the canonical serialization."""
    atomic_write_text(path, serialize_store(records, opaque))


def store_stats(
    records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()
) -> dict[str, dict[str, int]]:
    """Per-domain counts by label source over RAW lines (accumulation view):
    ``{domain: {"pending" | <label_source>: count}}`` plus ``_unparsed`` lines."""
    stats: dict[str, dict[str, int]] = {}
    for rec in records:
        source = rec.label_source if rec.label_source is not None else "pending"
        domain = stats.setdefault(rec.domain, {})
        domain[source] = domain.get(source, 0) + 1
    if opaque:
        stats[UNPARSED_STATS_KEY] = {"lines": len(opaque)}
    return stats


# A day is the smallest span over which a merge *rate* is meaningful; below it,
# velocity is reported unknown rather than extrapolated from noise.
_SECONDS_PER_DAY = 86_400.0


def _parse_ts(value: str) -> datetime | None:
    """Parse an ISO-8601 ``merged_at``; an unparseable stamp is ignored for velocity."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _velocity_per_day(records: Sequence[OutcomeRecord]) -> float | None:
    """Merge rate (records/day) across the ``merged_at`` span, or ``None`` when a rate
    cannot be established: fewer than two dated records, or a span under one day."""
    stamps = sorted(ts for ts in (_parse_ts(r.merged_at) for r in records) if ts is not None)
    if len(stamps) < 2:
        return None
    span_days = (stamps[-1] - stamps[0]).total_seconds() / _SECONDS_PER_DAY
    if span_days < 1.0:
        return None
    return (len(stamps) - 1) / span_days


def soak_progress(
    records: Sequence[OutcomeRecord],
    target: int,
    *,
    audit_floor: int = AuditConfig.per_domain_floor,
) -> dict[str, object]:
    """Soak-observability summary over raw outcome records (F-040).

    Pure and read-only: never mutates ``records``; touches no git or TCB state.
    ``audit_floor`` defaults to the audit sampler's per-domain floor (a config
    field, not a literal) — a domain stays flagged cold-start until it has that
    many HUMAN_AUDIT records, the only label source that feeds tau/health.
    """
    labeled = sum(1 for r in records if r.label is not None)
    human = [r for r in records if r.label_source == LabelSource.HUMAN_AUDIT.value]
    audits_by_domain: dict[str, int] = {}
    for rec in human:
        audits_by_domain[rec.domain] = audits_by_domain.get(rec.domain, 0) + 1
    cold_start = {
        domain: audits_by_domain.get(domain, 0) < audit_floor
        for domain in sorted({r.domain for r in records})
    }
    total = len(records)
    shortfall = max(0, target - total)
    velocity = _velocity_per_day(records)
    return {
        "total": total,
        "pending": total - labeled,
        "labeled": labeled,
        "human_audit": len(human),
        "per_domain_cold_start": cold_start,
        "n_vs_target": {"n": total, "target": target, "shortfall": shortfall},
        "velocity_per_day": velocity,
        "days_to_target": None if not velocity else shortfall / velocity,
    }
