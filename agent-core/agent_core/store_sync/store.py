"""Local outcome-store file I/O and per-domain statistics (no git).

An absent store file is an empty store, never an error. Writes are atomic
(tmp + ``os.replace``) so a crashed run can never leave a half-written store.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Sequence
from pathlib import Path

from ..outcome_store import OutcomeRecord
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
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(serialize_store(records, opaque), encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


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
