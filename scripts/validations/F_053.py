#!/usr/bin/env python3
"""Validation script for F-053 — matrix completeness: derived census, dim floors, artifact.

Checks:
    1. The generated coverage artifact exists and carries the GENERATED header.
    2. `python tests/test_matrix_coverage.py --check` exits 0 — the committed artifact
       matches an in-memory regeneration AND (transitively, because the guard suite
       enforces it) every registered component meets its kind's dimension floor.
    3. No designated registry class parametrizes over constant literals (any nesting) —
       asserted via the guard library's own detector, imported rather than restated
       (the F-052 no-restatement principle; a second copy would recreate exactly the
       divergence this feature exists to prevent).
    4. The policy tables are structurally sound: every core registry kind has a
       REQUIRED_DIMS floor, and the frozen alias map covers the same kinds.
    5. `eval-harness-ci.yml` path filters include the generated artifact on BOTH the
       push and pull_request triggers, so a hand edit to the doc alone still runs the
       freshness gate (the F-052 reachability lesson, applied proactively).

Deterministic and offline: reads files, imports the guard library, and runs one local
subprocess (the guard CLI); no network.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS, _ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_DOC_REL = os.path.join("docs", "matrix-coverage.md")
_CI_WORKFLOW_REL = os.path.join(".github", "workflows", "eval-harness-ci.yml")
_CORE_KINDS = frozenset({"scorer", "judge", "dataset", "target", "sink"})


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. The artifact exists and is marked generated.
    doc_path = os.path.join(_ROOT, _DOC_REL)
    doc_exists = os.path.exists(doc_path)
    _check(doc_exists, f"{_DOC_REL} exists", errors)
    if doc_exists:
        with open(doc_path, encoding="utf-8") as fh:
            first_line = fh.readline()
        _check(
            "GENERATED FILE" in first_line,
            f"{_DOC_REL} carries the GENERATED header on line 1",
            errors,
        )

    # 2. The guard CLI's freshness check passes (regenerate in memory, exact compare).
    completed = subprocess.run(
        [sys.executable, os.path.join("tests", "test_matrix_coverage.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=120,
    )
    _check(
        completed.returncode == 0,
        "python tests/test_matrix_coverage.py --check exits 0 "
        f"(exit {completed.returncode}; stdout: {completed.stdout.strip()[:200]})",
        errors,
    )

    # 3 + 4. Imported from the guard library — never restated here.
    from tests import _matrix_coverage as mc

    violations = mc.literal_parametrize_violations(mc.matrix_files())
    _check(
        not violations,
        "no designated registry class parametrizes over constant literals"
        + ("" if not violations else f": {violations}"),
        errors,
    )
    _check(
        set(mc.REQUIRED_DIMS) >= _CORE_KINDS,
        f"REQUIRED_DIMS covers every core registry kind {sorted(_CORE_KINDS)}",
        errors,
    )
    _check(
        set(mc.FROZEN_ALIAS_MAP) == set(mc.REQUIRED_DIMS),
        "FROZEN_ALIAS_MAP freezes the same kinds REQUIRED_DIMS floors",
        errors,
    )
    _check(
        all(reason.strip() for reason in mc.WAIVED.values()),
        "every waiver carries a non-empty reason",
        errors,
    )

    # 5. Reachability: the generated doc is in eval-harness-ci's path filters (push AND
    # pull_request), so a doc-only hand edit triggers the suite and the freshness gate.
    with open(os.path.join(_ROOT, _CI_WORKFLOW_REL), encoding="utf-8") as fh:
        workflow = fh.read()
    _check(
        workflow.count("docs/matrix-coverage.md") >= 2,
        f"{_CI_WORKFLOW_REL} lists docs/matrix-coverage.md in both push and pull_request paths",
        errors,
    )

    return report(logger, "F-053", errors)


if __name__ == "__main__":
    raise SystemExit(main())
