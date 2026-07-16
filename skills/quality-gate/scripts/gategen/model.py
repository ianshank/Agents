"""Deterministic facts the quality-gate script needs, derived from a project's files.

Scoped to what a gate must run: lint, type-check, tests, and a coverage threshold. Kept
deliberately separate from other skills' detectors so this skill stays self-contained and
independently vendorable (the repo duplicates helper code on purpose; see the skill-script
drift guard).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateFacts:
    """Everything the gate renderer needs, all derived deterministically."""

    python: str = "python3"
    has_ruff: bool = False
    type_checker: str | None = None  # "mypy" | "pyright" | None
    typecheck_paths: str = "."
    has_pytest: bool = False
    has_pytest_cov: bool = False
    coverage_source: str = "."
    cov_fail_under: int = 0

    @property
    def has_any_step(self) -> bool:
        """True when at least one gate step is emittable (else the gate is meaningless)."""
        return bool(self.has_ruff or self.type_checker or self.has_pytest)
