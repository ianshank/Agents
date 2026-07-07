"""Atomic text-file writes shared across agent_core.

Write to a sibling ``<name>.tmp`` then ``os.replace`` it over the target, so a crashed
or interrupted write never leaves a half-written file in place; the temp file is removed
if the write or rename fails. Extracted so the ``persistence`` and ``store_sync`` copies of
this idiom cannot drift (they had — one logged the failure, the other did not).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from .logging_util import get_logger

logger = get_logger(__name__)


def atomic_write_text(path: str | Path, text: str) -> None:
    """Atomically replace *path* with *text* (UTF-8).

    Writes ``<path>.tmp`` then ``os.replace``s it over *path*. On any failure the temp
    file is removed and the original error re-raised, so callers see the failure and the
    on-disk file is never left partially written.
    """
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        logger.warning("atomic write to %s failed; removing temp file", target)
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
