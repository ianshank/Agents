#!/usr/bin/env python3
"""Auto-fix loop — DESIGN-ONLY, DISABLED. Do not enable without human sign-off.

An automated "fix-until-green" loop is the single highest-Goodhart-risk component in
an eval harness: the cheapest path to green is to weaken the evaluation, not the code.
This module therefore ships **inert**: ``FIX_ENABLED`` is ``False``, nothing wires it
into CI, and it physically cannot write to a protected (eval-defining) path.

See ``docs/decisions/0004-auto-fix-loop.md`` for the full design and the human
checklist required to turn it on.

What is implemented and tested here (so the safety properties are real, not aspirational):
    * ``ScopeGuard`` — rejects any write to a protected path.
    * ``run_fix_loop`` — refuses to start while disabled or if the Phase-2 guard is
      missing; re-derives the verdict from a clean re-evaluation each cycle; and
      escalates (raises) when ``max_cycles`` is exhausted.

What is intentionally *not* here: any enabling switch, CI hook, live-judge/Langfuse
evaluation, or commit-message "verified" token. Provenance remains the human/CI-written
``implemented_in`` SHA.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scripts.eval_protected_paths import is_protected

logger = logging.getLogger(__name__)

# Hard off-switch. Flipping this is a human decision gated by the ADR checklist.
FIX_ENABLED: bool = False

DEFAULT_MAX_CYCLES: int = 5


class ProtectedPathError(PermissionError):
    """Raised when a fix attempts to write to a protected eval-defining path."""


class FixLoopDisabledError(RuntimeError):
    """Raised when the loop is invoked while disabled or unsafe to run."""


class FixLoopExhaustedError(RuntimeError):
    """Raised when the loop reaches ``max_cycles`` without a passing verdict."""


@dataclass
class ScopeGuard:
    """Confines all writes to implementation modules; protected paths are read-only.

    The guard is the OS/tooling-layer enforcement referenced by the ADR: a fixer must
    route every write through :meth:`assert_writable` (or :meth:`write_text`), which
    raises before any protected path can be modified.
    """

    root: Path = field(default_factory=Path.cwd)

    def assert_writable(self, path: str | Path) -> Path:
        """Return a resolved path if writable; raise :class:`ProtectedPathError` otherwise.

        A fixer may only ever write *repo-relative* paths inside the tree, and never a
        protected eval-defining path. Absolute paths are rejected outright (so a fixer
        cannot rely on absolute addressing even within the repo); ``..`` traversal that
        escapes the root is rejected; and protected paths are rejected.
        """
        candidate = Path(path)
        if candidate.is_absolute():
            raise ProtectedPathError(f"refusing absolute path; use a repo-relative path: {path}")
        resolved_root = self.root.resolve()
        resolved = (resolved_root / candidate).resolve()
        try:
            rel = resolved.relative_to(resolved_root).as_posix()
        except ValueError as exc:
            raise ProtectedPathError(f"refusing to write outside the project root: {path}") from exc
        if is_protected(rel):
            raise ProtectedPathError(f"refusing to write protected eval-defining path: {rel}")
        return resolved

    def write_text(self, path: str | Path, content: str) -> Path:
        """Write *content* to *path* only if it is inside root and outside the protected set."""
        target = self.assert_writable(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


@dataclass
class FixOutcome:
    """Result of a completed (or escalated) fix loop run."""

    passed: bool
    cycles: int
    notes: list[str] = field(default_factory=list)


def _guard_present(root: Path) -> bool:
    """True iff the Phase-2 protected-path guard exists — a precondition to running."""
    return (root / "scripts" / "check_protected_changes.py").is_file() and (
        root / "scripts" / "eval_protected_paths.py"
    ).is_file()


def run_fix_loop(
    *,
    evaluate: Callable[[], bool],
    apply_fix: Callable[[ScopeGuard, int], None],
    max_cycles: int = DEFAULT_MAX_CYCLES,
    enabled: bool = FIX_ENABLED,
    root: Path | None = None,
) -> FixOutcome:
    """Drive a bounded fix loop. INERT by default — see module docstring.

    Parameters
    ----------
    evaluate:
        Re-derives the verdict from a *clean* re-run; the loop never trusts a fixer's
        self-report. Must target the offline deterministic suite only.
    apply_fix:
        Applies one round of changes, receiving a :class:`ScopeGuard` (so it cannot
        touch protected paths) and the current cycle index.
    max_cycles:
        Upper bound on attempts before escalation.
    enabled:
        Defaults to the module-level ``FIX_ENABLED`` (``False``). The loop refuses to
        run unless explicitly enabled *and* the Phase-2 guard is present.
    """
    root = root or Path.cwd()
    if not enabled:
        raise FixLoopDisabledError(
            "auto-fix loop is disabled (FIX_ENABLED is False); enabling requires the "
            "human sign-off described in docs/decisions/0004-auto-fix-loop.md"
        )
    if not _guard_present(root):
        raise FixLoopDisabledError("Phase-2 protected-path guard not found; refusing to run the fix loop")
    if max_cycles < 1:
        raise ValueError("max_cycles must be >= 1")

    guard = ScopeGuard(root=root)
    notes: list[str] = []

    # Verdict is always re-derived from a clean re-evaluation — never self-reported.
    if evaluate():
        return FixOutcome(passed=True, cycles=0, notes=["already passing"])

    for cycle in range(1, max_cycles + 1):
        logger.info("fix-loop cycle %d/%d", cycle, max_cycles)
        apply_fix(guard, cycle)
        if evaluate():
            notes.append(f"passed after cycle {cycle}")
            return FixOutcome(passed=True, cycles=cycle, notes=notes)
        notes.append(f"cycle {cycle} did not pass")

    raise FixLoopExhaustedError(f"fix loop exhausted {max_cycles} cycles without a passing verdict; escalating")


def main() -> int:
    """Refuse to run — this entry point exists only to make the disabled state explicit."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s")
    print(
        "fix_loop is DISABLED by design (FIX_ENABLED=False). See docs/decisions/0004-auto-fix-loop.md before enabling."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
