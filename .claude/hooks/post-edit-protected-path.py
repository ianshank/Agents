#!/usr/bin/env python3
"""PostToolUse hook: say so, at the edit, when a file is an eval-integrity protected path.

WHY THIS EXISTS. `scripts/eval_protected_paths.py` defines the surface that may only change
under the `eval-change-approved` label plus a CODEOWNER's review, because the cheapest way
to make a failing eval pass is to weaken the evaluation rather than fix the code. Every
enforcement point for that rule is remote and late: `check_protected_changes.py` runs in
CI, on a diff, after a pull request exists. Locally there is no signal at all -- a session
can edit `features.yaml`, a scorer, a gate threshold or a corpus and only discover the
review obligation when a red check appears, by which point the change is entangled with a
dozen unprotected ones and cannot be split.

Reporting it at the edit is what makes the split cheap: an unprotected change can still be
lifted into its own pull request while it is one file old.

Deliberately ADVISORY. It never blocks: the protected-path rule is about who reviews a
change, not about whether it may be written, and a hook that refused the edit would make
legitimate protected work impossible from a session that has the label. The CI guard
remains the enforcement point; this is only the early warning.

Fail-OPEN, mirroring `post-edit-size-budget.py`: every path out of this script exits 0 and
a finding is returned as `additionalContext`, never as a block.

Imports the real module rather than restating its globs -- a hook with its own copy of the
pattern list is a second source of truth that drifts, which is the failure this repository
has already fixed twice elsewhere (`check_guard_reachability.py`, `test_required_check_stubs.py`).
"""

from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_REPO_ROOT, "scripts")

#: Used only if `check_protected_changes.DEFAULT_APPROVAL_LABEL` cannot be imported. The
#: guard is the source of truth; this exists so a missing import degrades to a slightly
#: less precise message rather than to no message.
_FALLBACK_LABEL = "eval-change-approved"


def _finding(file_path: str) -> str | None:
    """A warning for a protected path, or None. Returns None if the guard cannot be read."""
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    try:
        import eval_protected_paths as epp
    except Exception:
        return None  # the guard is the source of truth; without it this hook has no opinion

    try:
        relative = os.path.relpath(os.path.abspath(file_path), _REPO_ROOT)
    except ValueError:  # a different drive on Windows: not in this repository
        return None
    if relative.startswith(".."):
        return None
    if not epp.is_protected(relative.replace(os.sep, "/")):
        return None

    try:
        import check_protected_changes as guard

        label = guard.DEFAULT_APPROVAL_LABEL
    except Exception:
        label = _FALLBACK_LABEL
    return (
        f"protected-path: {relative} is an eval-integrity protected path "
        f"(scripts/eval_protected_paths.py). Merging it needs the `{label}` label and a "
        "CODEOWNER review. If the rest of this change is unprotected, splitting it into its "
        "own pull request now is far cheaper than after the two are entangled."
    )


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        file_path = str((event.get("tool_input") or {}).get("file_path") or "")
        if not file_path:
            return 0
        finding = _finding(file_path)
        if finding:
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": finding,
                }
            }
            print(json.dumps(payload))
    except Exception:
        pass  # fail open: an advisory check must never block or crash a real edit
    return 0


if __name__ == "__main__":
    sys.exit(main())
