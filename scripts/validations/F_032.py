#!/usr/bin/env python3
"""Validation script for F-032 — outcome-store persistence seam (store_sync).

Deterministic and offline: reads source/workflow files only, runs nothing.

    1. ``agent_core/store_sync.py`` exists with the load-bearing pieces:
       ``StoreSyncConfig``, ``merge_records`` (canonical merge), plumbing
       commits (``commit-tree``), retry tunable, and ``[skip ci]`` hygiene.
    2. Every workflow that references the outcome store also invokes
       ``agent_core.store_sync`` (no workflow reads/writes the store raw).
    3. No ``pull_request``-triggered workflow invokes the push path —
       PR-time sync is read-only (ADR 0018; fork tokens are read-only).
    4. agent-core stays a zero-runtime-dependency package (the sync must not
       drag in a git library or HTTP client).
    5. The real-git test suite exists.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_STORE_REF = "merge_outcomes.jsonl"
_SYNC_REF = "agent_core.store_sync"
_WORKFLOWS_DIR = os.path.join(_ROOT, ".github", "workflows")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def _workflow_triggers(text: str) -> set[str]:
    """Trigger names of a workflow file (yaml 'on:' keys; parses True as 'on')."""
    doc = yaml.safe_load(text)
    triggers = doc.get("on", doc.get(True, {}))
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, list):
        return set(triggers)
    return set(triggers or {})


def validate_f032() -> int:
    configure_logging()
    errors: list[str] = []

    module = _read(os.path.join("agent-core", "agent_core", "store_sync.py"))
    for needle, why in [
        ("class StoreSyncConfig", "config dataclass exists"),
        ("def merge_records", "canonical merge exists"),
        ("commit-tree", "plumbing commit path exists (worktree never touched)"),
        ("max_push_retries", "bounded retry tunable exists"),
        ("[skip ci]", "data-branch commits skip CI"),
        ("FETCH_HEAD", "fetch-gated FETCH_HEAD read exists"),
    ]:
        _check(needle in module, f"store_sync.py: {why}", errors)

    _check(
        os.path.exists(os.path.join(_ROOT, "agent-core", "tests", "test_store_sync.py")),
        "real-git test suite exists (agent-core/tests/test_store_sync.py)",
        errors,
    )

    pyproject = _read(os.path.join("agent-core", "pyproject.toml"))
    _check(
        "\ndependencies" not in pyproject.replace("optional-dependencies", ""),
        "agent-core keeps zero runtime dependencies",
        errors,
    )

    for name in sorted(os.listdir(_WORKFLOWS_DIR)):
        if not name.endswith((".yml", ".yaml")):
            continue
        text = _read(os.path.join(".github", "workflows", name))
        if _STORE_REF in text:
            _check(
                _SYNC_REF in text,
                f"{name}: references the store and invokes {_SYNC_REF}",
                errors,
            )
        if "pull_request" in _workflow_triggers(text):
            _check(
                f"{_SYNC_REF} push" not in text,
                f"{name}: pull_request-triggered workflow never pushes the store",
                errors,
            )

    return report(logger, "F-032", errors)


def main() -> int:
    return validate_f032()


if __name__ == "__main__":
    sys.exit(main())
