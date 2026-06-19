"""Diff the actual component graph against the declared edges.

``undocumented`` edges (present in code, absent from the manifest) are the drift
that FAILS the gate. ``unused`` edges (declared but not observed) are reported as
a warning only — they may be aspirational or simply stale, and silently failing
on them would punish honest manifests. Results are sorted for deterministic
output.
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import Edge


@dataclass
class DiffResult:
    """Outcome of comparing actual vs declared component edges."""

    undocumented: list[Edge]  # actual - declared  => gate failure
    unused: list[Edge]        # declared - actual  => warning only

    @property
    def has_drift(self) -> bool:
        return bool(self.undocumented)


def diff_edges(actual: set[Edge], declared: set[Edge]) -> DiffResult:
    """Classify the symmetric difference of actual and declared edges."""
    undocumented = sorted(actual - declared)
    unused = sorted(declared - actual)
    return DiffResult(undocumented=undocumented, unused=unused)


def format_report(diff: DiffResult) -> str:
    """Render a human-readable report for stderr."""
    lines: list[str] = []
    if diff.undocumented:
        lines.append("Undocumented dependencies (architecture drift):")
        for src, dst in diff.undocumented:
            lines.append(f"  - {src} -> {dst}")
        lines.append("")
        lines.append(
            "Each edge above exists in the code but not in the manifest. If the "
            "dependency is intended, add it to 'dependencies' and regenerate the "
            "diagram; if it is a mistake, fix the import."
        )
    else:
        lines.append("No undocumented dependencies. Architecture matches the manifest.")
    if diff.unused:
        lines.append("")
        lines.append("Declared but unused dependencies (warning only):")
        for src, dst in diff.unused:
            lines.append(f"  [warn] {src} -> {dst}")
    return "\n".join(lines)
