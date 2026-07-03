"""§8 atomic write: write to a sibling temp dir, validate, then swap into place.

The temp dir is created as a sibling of ``out`` (same parent) so os.replace cannot cross
filesystems (revision 5). The bak->replace sequence is per-step atomic, not atomic as a
whole: there is a brief window where the old output is renamed away before the new one lands.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

CANONICAL_DIR = "canonical"
GROUND_TRUTH_DIR = "ground_truth"
VIEWS_DIR = "views"
VALIDATION_DIR = "validation"
PROVENANCE_DIR = "provenance"
# Bound on unique temp-dir name attempts: pid + millisecond timestamp + counter make a
# collision essentially impossible, so hitting the bound means something is wrong with
# the parent directory, not bad luck.
_MAX_TEMP_DIR_ATTEMPTS = 100


def _write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _strip_internal(canonical: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in canonical.items() if not k.startswith("_")}


def write_package(
    tmp_dir: str,
    *,
    canonicals: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    views: dict[str, dict[str, Any]],
    provenance: list[dict[str, Any]],
) -> None:
    """Write every package artifact under ``tmp_dir`` (manifest/validation written later)."""
    _write_jsonl(
        os.path.join(tmp_dir, CANONICAL_DIR, "scenarios.jsonl"),
        [_strip_internal(c) for c in canonicals],
    )
    _write_jsonl(os.path.join(tmp_dir, GROUND_TRUTH_DIR, "mappings.jsonl"), ground_truth)
    for name, view in views.items():
        _write_jsonl(os.path.join(tmp_dir, VIEWS_DIR, f"{name}.jsonl"), view["records"])
    _write_jsonl(os.path.join(tmp_dir, PROVENANCE_DIR, "source_index.jsonl"), provenance)
    os.makedirs(os.path.join(tmp_dir, VALIDATION_DIR), exist_ok=True)


def make_temp_dir(out: str) -> str:
    """Create a unique sibling temp dir on the same filesystem as ``out``.

    The name includes the pid and a counter so concurrent forge runs never collide; we create
    with os.makedirs (failing if it exists) rather than deleting any directory that is already
    there, which could be another run's live staging area.
    """
    parent = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(parent, exist_ok=True)
    base = os.path.basename(os.path.abspath(out))
    for attempt in range(_MAX_TEMP_DIR_ATTEMPTS):
        tmp = os.path.join(parent, f"{base}.tmp.{int(time.time() * 1000)}.{os.getpid()}.{attempt}")
        try:
            os.makedirs(tmp)
            return tmp
        except FileExistsError:
            continue
    logger.warning("exhausted %d temp-dir name attempts next to %s", _MAX_TEMP_DIR_ATTEMPTS, out)
    raise OSError(f"could not allocate a unique temp dir next to {out!r}")


def commit(tmp_dir: str, out: str) -> str | None:
    """Swap tmp into place. Returns the backup path if an existing output was preserved."""
    out_abs = os.path.abspath(out)
    backup: str | None = None
    if os.path.exists(out_abs):
        backup = f"{out_abs}.bak.{int(time.time() * 1000)}"
        os.rename(out_abs, backup)
    try:
        os.replace(tmp_dir, out_abs)
    except OSError:
        # Honor the contract: restore the original if the swap fails after the backup rename.
        if backup and os.path.exists(backup) and not os.path.exists(out_abs):
            logger.warning("swap into %s failed; restoring previous output from backup", out_abs)
            os.rename(backup, out_abs)
        raise
    logger.debug("package committed to %s (backup=%s)", out_abs, backup)
    return backup
