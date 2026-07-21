#!/usr/bin/env python3
"""Validation script for F-039 — public-surface backwards-compat guard + protected-path gap fix.

Asserts two related invariants stay in place:
    1. The append-only ``__all__`` guard (``tests/test_public_surface.py``) and its frozen
       baseline exist at the root and are byte-identically duplicated (drift-guarded) into
       each of the four sibling packages' own ``tests/`` directories, since each package runs
       its own isolated pytest suite and the guard must be self-contained there.
    2. The eval-integrity protected-path set (``scripts/eval_protected_paths.py``) covers
       those same four sibling ``tests/`` directories — "tests/**" alone only anchors the root
       suite (``^tests/.*$``), so the sibling copies (and every other test in those packages)
       were previously unprotected. ``.github/CODEOWNERS`` must mirror the same coverage.

Deterministic and offline: reads config/source files and the in-process pattern list; runs
nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import json
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_PACKAGES = ("agent-core", "behavioral-regression", "flow-corpus", "flow-protocol")
_GUARD_FILE = "test_public_surface.py"
_BASELINE_FILE = "public_surface_baseline.json"


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. Guard + baseline exist at the root and in every sibling package.
    for pkg in ("", *_PACKAGES):
        guard_rel = os.path.join(pkg, "tests", _GUARD_FILE)
        baseline_rel = os.path.join(pkg, "tests", _BASELINE_FILE)
        label = pkg or "root"
        _check(os.path.exists(os.path.join(_ROOT, guard_rel)), f"{label}: {_GUARD_FILE} exists", errors)
        _check(os.path.exists(os.path.join(_ROOT, baseline_rel)), f"{label}: {_BASELINE_FILE} exists", errors)
        if os.path.exists(os.path.join(_ROOT, baseline_rel)):
            with open(os.path.join(_ROOT, baseline_rel), encoding="utf-8") as fh:
                data = json.load(fh)
            _check(
                isinstance(data, dict) and set(data) == {"packages", "surface"},
                f"{label}: {_BASELINE_FILE} has the 'packages'/'surface' shape",
                errors,
            )
            _check(bool(data.get("surface")), f"{label}: {_BASELINE_FILE} freezes a non-empty surface", errors)

    # 2. The drift guard tracks the 4 sibling copies against the root canonical.
    import check_skill_script_drift as drift

    canonical = os.path.join("tests", _GUARD_FILE)
    tracked = drift.TRACKED_DUPLICATES.get(canonical, ())
    expected_copies = {os.path.join(pkg, "tests", _GUARD_FILE) for pkg in _PACKAGES}
    _check(
        set(tracked) == expected_copies,
        f"check_skill_script_drift tracks all 4 sibling {_GUARD_FILE} copies against the root canonical",
        errors,
    )
    drift_results = drift.check_drift({canonical: tracked} if tracked else {})
    _check(
        bool(drift_results) and all(r.ok for r in drift_results),
        "the tracked public-surface-guard copies are byte-identical to the root canonical (no drift)",
        errors,
    )

    # 3. The 4 sibling test/ directories are protected paths (tests/** alone only anchors root).
    import eval_protected_paths as epp

    for pkg in _PACKAGES:
        pattern = f"{pkg}/tests/**"
        _check(
            pattern in epp.PROTECTED_PATTERNS, f"eval_protected_paths.PROTECTED_PATTERNS includes {pattern!r}", errors
        )
        _check(
            epp.is_protected(os.path.join(pkg, "tests", "anything.py")),
            f"{pkg}/tests/ is_protected() (a representative path resolves True)",
            errors,
        )

    # 4. CODEOWNERS mirrors the same 4 entries.
    codeowners = _read(os.path.join(".github", "CODEOWNERS"))
    for pkg in _PACKAGES:
        _check(f"/{pkg}/tests/" in codeowners, f".github/CODEOWNERS covers /{pkg}/tests/", errors)

    return report(logger, "F-039", errors)


if __name__ == "__main__":
    raise SystemExit(main())
