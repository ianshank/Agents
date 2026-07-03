"""Shared strict JSONL reading for append-only stores.

One canonical implementation of the "one record per non-blank line" read idiom
so stores don't each hand-roll it. Strict by design: a malformed line raises,
because an append-only audit store with a corrupt line is a store whose
integrity guarantee is already gone — silently skipping would hide that.

Deliberately NOT used by readers with different semantics:

* :mod:`agent_core.store_sync` must preserve unparseable ("opaque") lines
  verbatim so a pull/push round-trip never rewrites history it does not own.
* ``eval_harness`` dataset loaders track per-line indexes for item ids and do
  not hard-depend on agent-core (the packages are joined by a soft seam).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

from .logging_util import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def iter_jsonl(path: str | Path, factory: Callable[[str], T]) -> Iterator[T]:
    """Yield ``factory(line)`` for each non-blank line of ``path``.

    Streams line-by-line (append-only stores grow unbounded, so the file is
    never materialised as one string). A missing file yields nothing — for an
    append-only store, "never written yet" and "empty" are the same state.
    """
    p = Path(path)
    if not p.exists():
        logger.debug("jsonl store %s does not exist; yielding no records", p)
        return
    count = 0
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield factory(line)
                count += 1
    logger.debug("read %d records from %s", count, p)


def read_jsonl(path: str | Path, factory: Callable[[str], T]) -> list[T]:
    """Materialised :func:`iter_jsonl` for callers that need the whole store."""
    return list(iter_jsonl(path, factory))
