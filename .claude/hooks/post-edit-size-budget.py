#!/usr/bin/env python3
"""PostToolUse hook: flags a just-edited Python file once it (or the single-file
scan `check_size_budget.py --root <file>` performs) crosses the 500-line hard
budget CI enforces (`scripts/check_size_budget.py`, `docs/decisions/0019-size-
budget-gate.md`).

WHY THIS EXISTS. The gate itself already runs in CI (`quality-gates.yml`) and via
`quality-gate.sh all`/`make check-all` locally -- this hook does not replace either.
It exists because both of those only run at the *end* of a batch of edits: a file
can cross the budget several edits before anyone notices, at which point the fix is
a scramble (see `scripts/validations/F_057.py`'s own history — it crossed 500 lines
mid-session and needed a DRY pass to get back under, discovered only once the full
gate finally ran). Catching it at the edit that crosses the line, while the change
is still fresh, is cheaper than catching it later.

Fail-OPEN, advisory only, mirroring `claude-foundation/hooks/post_edit_verify.py`'s
own contract (ADR 0002 in that package): every path out of this script exits 0, and
a finding is returned to the model as `additionalContext`, never a block. Root-owned
rather than a dependency on `claude-foundation/` (slated for its own-repo extraction
— NEXT_STEPS.md's M7 entry) so this hook works the same whether or not a session has
that plugin loaded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _check(file_path: str) -> str | None:
    """Run the real gate script, scoped to just *file_path*; return a finding or None."""
    checker = os.path.join(_REPO_ROOT, "scripts", "check_size_budget.py")
    result = subprocess.run(
        [sys.executable, checker, "--root", file_path],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=_REPO_ROOT,
    )
    if result.returncode == 0:
        return None
    tail = (result.stdout + result.stderr).strip()
    return f"post-edit-size-budget: {file_path} now exceeds the 500-line file budget.\n{tail}"


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        file_path = str((event.get("tool_input") or {}).get("file_path") or "")
        if not file_path.endswith(".py") or not os.path.isfile(file_path):
            return 0
        finding = _check(file_path)
        if finding:
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": finding,
                }
            }
            print(json.dumps(payload))
    except Exception:
        pass  # fail open: this advisory check must never block or crash a real edit
    return 0


if __name__ == "__main__":
    sys.exit(main())
