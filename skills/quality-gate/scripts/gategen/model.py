"""Deterministic facts the quality-gate script needs, derived from a project's files.

Scoped to what a gate must run: lint, type-check, tests, and a coverage threshold. Kept
deliberately separate from other skills' detectors so this skill stays self-contained and
independently vendorable (the repo duplicates helper code on purpose; see the skill-script
drift guard).
"""

from __future__ import annotations

from dataclasses import dataclass

# Field names whose values are path/source collections. Single strings are accepted and
# coerced for backwards compatibility with the 1.0.x single-string fields.
_TUPLE_FIELDS = ("lint_paths", "typecheck_paths", "coverage_source")


@dataclass(frozen=True)
class GateFacts:
    """Everything the gate renderer needs, all derived deterministically.

    ``lint_paths``, ``typecheck_paths`` and ``coverage_source`` are tuples so a gate can
    lint several trees, type-check several roots (e.g. mypy run per-path to avoid
    module-name collisions), and measure coverage over several sources. A plain string is
    accepted anywhere a tuple is expected (coerced in ``__post_init__``) so 1.0.x callers
    keep working unchanged.
    """

    # Field ORDER is part of the 1.0.x contract (positional constructors): new fields are
    # appended at the end, never inserted mid-list.
    python: str = "python3"
    has_ruff: bool = False
    type_checker: str | None = None  # "mypy" | "pyright" | None
    typecheck_paths: tuple[str, ...] = (".",)
    has_pytest: bool = False
    has_pytest_cov: bool = False
    coverage_source: tuple[str, ...] = (".",)
    cov_fail_under: int = 0
    lint_paths: tuple[str, ...] = (".",)

    def __post_init__(self) -> None:
        # Backwards compatibility: 1.0.x typed these as single strings. Coerce str -> 1-tuple
        # (and any iterable -> tuple) so old constructors and new detection both normalize.
        for name in _TUPLE_FIELDS:
            value = getattr(self, name)
            if isinstance(value, str):
                object.__setattr__(self, name, (value,))
            else:
                object.__setattr__(self, name, tuple(value))
        # An EMPTY collection would render a step with no targets/commands (a fabricated
        # no-op that "passes"); normalize every path field to the whole-tree default so all
        # three tuple fields share one uniform "empty means '.'" rule.
        for name in _TUPLE_FIELDS:
            if not getattr(self, name):
                object.__setattr__(self, name, (".",))

    @property
    def has_any_step(self) -> bool:
        """True when at least one gate step is emittable (else the gate is meaningless).

        Includes ``has_pytest_cov``: a project can supply a coverage step (pytest-cov declared)
        without a separate pytest signal, and the renderer would still emit that step.
        """
        return bool(self.has_ruff or self.type_checker or self.has_pytest or self.has_pytest_cov)
