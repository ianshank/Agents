"""Pure merge/serialization core for the outcome store (no I/O, no git).

The canonical order and dedup rules here are load-bearing for ADR 0018: any
interleaving of the same record sets must serialize byte-identically, because
``OutcomeStore.resolved()`` resolves passive labels by file position.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from ..logging_util import get_logger
from ..outcome_store import OutcomeRecord

logger = get_logger(__name__)


def canonical_key(rec: OutcomeRecord) -> tuple[str, bool, str, str, str, str]:
    """Deterministic TOTAL order: pending lines precede labels at the same merge
    time, labels order by ``labeled_at`` — so ``resolved()``'s position-dependent
    "latest labeled wins" is byte-reproducible from any interleaving. The full
    canonical JSON is the final tie-break: without it, records differing only in
    an unkeyed field (e.g. domain) would sort by insertion order."""
    return (
        rec.merged_at,
        rec.labeled_at is not None,
        rec.labeled_at or "",
        rec.label_source or "",
        rec.change_id,
        rec.to_json(),
    )


def merge_records(*sets: Iterable[OutcomeRecord]) -> list[OutcomeRecord]:
    """Union of record sets, deduped by full canonical JSON, canonically sorted.

    Only byte-identical duplicate lines collapse; distinct records for the same
    change (a pending seed, a passive label, a human audit) all survive —
    precedence between them stays ``OutcomeStore.resolved()``'s job.
    """
    unique: dict[str, OutcomeRecord] = {}
    for records in sets:
        for rec in records:
            unique.setdefault(rec.to_json(), rec)
    return sorted(unique.values(), key=canonical_key)


def _parse_line(line: str) -> OutcomeRecord | None:
    """Strictly parse one store line; None means opaque (see merge_opaque).

    A malformed line or one carrying fields this reader doesn't know (an
    upgraded writer during a rolling upgrade) must NOT crash the pipeline —
    and must NOT be silently dropped either, or a subsequent push would
    delete it from the data branch. Opaque lines are preserved verbatim.
    """
    try:
        return OutcomeRecord(**json.loads(line))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("store-sync preserving unparseable line (%s): %.120s", exc, line)
        return None


def _split_lines(text: str) -> tuple[list[OutcomeRecord], list[str]]:
    records: list[OutcomeRecord] = []
    opaque: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = _parse_line(line)
        if rec is None:
            opaque.append(line)
        else:
            records.append(rec)
    return records, opaque


def merge_opaque(*sets: Iterable[str]) -> list[str]:
    """Union of opaque (unparseable-here) lines, deduped exactly, sorted.

    They serialize AFTER the parsed records: their canonical position cannot
    be computed without parsing, and the next upgraded writer re-canonicalizes
    the whole store anyway.
    """
    unique: set[str] = set()
    for lines in sets:
        unique.update(lines)
    return sorted(unique)


def serialize_store(records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()) -> str:
    body = "".join(rec.to_json() + "\n" for rec in records)
    return body + "".join(line + "\n" for line in opaque)
