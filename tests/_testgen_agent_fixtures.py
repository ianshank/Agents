"""Offline generator fixtures for ``testgen_agent`` (M8 + unit tests).

These live under ``tests.`` so ``EVAL_HARNESS_CALLABLE_TARGET_ALLOWLIST=tests``
(conftest) admits ``generator_path`` without allowlisting ``eval_harness``.
"""

from __future__ import annotations

from eval_harness.core.types import EvalItem

#: A suite that drives the input at which the M8 inline mutant diverges.
KILLING_SUITE = "from focal import add\n\ndef test_boundary():\n    assert add(2, 1) == -1\n"


class _NotAGenerator:
    """Non-callable whose defining module is this tests package (ADR 0039 origin check)."""


NOT_A_GENERATOR = _NotAGenerator()


def killing_suite(item: EvalItem) -> str:
    """Return a killing suite. Raises if the homework ``suite`` key is visible."""
    if "suite" in item.inputs:
        raise AssertionError("generator must not see inputs.suite")
    return KILLING_SUITE


def mutating_spy(item: EvalItem) -> str:
    """Mutate nested ``obligations`` on the view; isolation must keep the original intact."""
    obligations = item.inputs.get("obligations")
    if isinstance(obligations, list):
        obligations.append("MUTATED_BY_GENERATOR")
    return KILLING_SUITE
