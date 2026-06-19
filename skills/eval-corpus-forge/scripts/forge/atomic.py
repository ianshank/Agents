"""§8 atomic write: write to a sibling temp dir, validate, then swap into place.

The temp dir is created as a sibling of ``out`` (same parent) so os.replace cannot cross
filesystems (revision 5). The bak->replace sequence is per-step atomic, not atomic as a
whole: there is a brief window where the old output is renamed away before the new one lands.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

CANONICAL_DIR = "canonical"
GROUND_TRUTH_DIR = "ground_truth"
VIEWS_DIR = "views"
VALIDATION_DIR = "validation"
PROVENANCE_DIR = "provenance"


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
    """Create a sibling temp dir guaranteed to be on the same filesystem as ``out``."""
    parent = os.path.dirname(os.path.abspath(out)) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = os.path.join(parent, f"{os.path.basename(os.path.abspath(out))}.tmp.{int(time.time()*1000)}")
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    return tmp


def commit(tmp_dir: str, out: str) -> str | None:
    """Swap tmp into place. Returns the backup path if an existing output was preserved."""
    out_abs = os.path.abspath(out)
    backup: str | None = None
    if os.path.exists(out_abs):
        backup = f"{out_abs}.bak.{int(time.time()*1000)}"
        os.rename(out_abs, backup)
    try:
        os.replace(tmp_dir, out_abs)
    except OSError:
        # Honor the contract: restore the original if the swap fails after the backup rename.
        if backup and os.path.exists(backup) and not os.path.exists(out_abs):
            os.rename(backup, out_abs)
        raise
    return backup
