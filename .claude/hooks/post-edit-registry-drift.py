#!/usr/bin/env python3
"""PostToolUse hook: advisory check that detects registry-matrix drift when
component registrations or matrix obligations are edited.

Fail-OPEN, advisory only: exits 0 on all paths; emitted findings are returned
as additionalContext.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _check(file_path: str) -> str | None:
    """Run test_matrix_coverage.py --check if the edited file is an eval/matrix component."""
    norm = file_path.replace("\\", "/")
    if not (norm.startswith("src/eval_harness/") or "test_matrix" in norm or norm.endswith("features.yaml")):
        return None

    checker = os.path.join(_REPO_ROOT, "tests", "test_matrix_coverage.py")
    result = subprocess.run(
        [sys.executable, checker, "--check"],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=_REPO_ROOT,
    )
    if result.returncode == 0:
        return None
    return (
        f"post-edit-registry-drift: component registration or matrix coverage may have drifted.\n"
        f"Regenerate and commit: python tests/test_matrix_coverage.py --update\n"
        f"{(result.stdout + result.stderr).strip()}"
    )


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        file_path = str((event.get("tool_input") or {}).get("file_path") or "")
        rel_path = os.path.relpath(file_path, _REPO_ROOT) if os.path.isabs(file_path) else file_path
        finding = _check(rel_path)
        if finding:
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": finding,
                }
            }
            print(json.dumps(payload))
    except Exception:
        pass  # fail open: advisory check must never block
    return 0


if __name__ == "__main__":
    sys.exit(main())
