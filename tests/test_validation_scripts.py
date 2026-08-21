"""Smoke + coverage tests for the per-feature validation scripts.

These scripts are run end-to-end by ``scripts/validate.py`` in CI, but were not
coverage-measured. Importing each module and invoking ``main()`` here both
asserts they still pass and brings them (and the shared ``_common`` helper) under
the quality-gate tooling coverage floor.

Registration is explicit (import + parametrize + ids — no discovery): a new
validator must be added here AND to quality-gates.yml's ``--cov=`` list, or its
coverage silently never counts. F_058 enforces that the lists stay synchronized.
"""

from __future__ import annotations

import os
import sys

import pytest

_VALIDATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "validations")
if _VALIDATIONS not in sys.path:
    sys.path.insert(0, _VALIDATIONS)

import _common  # noqa: E402
import F_020  # noqa: E402
import F_021  # noqa: E402
import F_022  # noqa: E402
import F_023  # noqa: E402
import F_024  # noqa: E402
import F_025  # noqa: E402
import F_026  # noqa: E402
import F_027  # noqa: E402
import F_028  # noqa: E402
import F_029  # noqa: E402
import F_030  # noqa: E402
import F_031  # noqa: E402
import F_032  # noqa: E402
import F_033  # noqa: E402
import F_034  # noqa: E402
import F_035  # noqa: E402
import F_037  # noqa: E402
import F_038  # noqa: E402
import F_039  # noqa: E402
import F_040  # noqa: E402
import F_041  # noqa: E402
import F_042  # noqa: E402
import F_043  # noqa: E402
import F_044  # noqa: E402
import F_045  # noqa: E402
import F_046  # noqa: E402
import F_047  # noqa: E402
import F_048  # noqa: E402
import F_049  # noqa: E402
import F_050  # noqa: E402
import F_051  # noqa: E402
import F_052  # noqa: E402
import F_053  # noqa: E402
import F_054  # noqa: E402
import F_055  # noqa: E402
import F_056  # noqa: E402
import F_057  # noqa: E402
import F_058  # noqa: E402
import F_059  # noqa: E402
import F_060  # noqa: E402

#: Single source of truth for which validators this file exercises. The ids are derived
#: from each module's own ``__name__`` rather than restated, so the list cannot drift
#: from its own labels.
_VALIDATOR_MODULES = (
    F_020,
    F_021,
    F_022,
    F_023,
    F_024,
    F_025,
    F_026,
    F_027,
    F_028,
    F_029,
    F_030,
    F_031,
    F_032,
    F_033,
    F_034,
    F_035,
    F_037,
    F_038,
    F_039,
    F_040,
    F_041,
    F_042,
    F_043,
    F_044,
    F_045,
    F_046,
    F_047,
    F_048,
    F_049,
    F_050,
    F_051,
    F_052,
    F_053,
    F_054,
    F_055,
    F_056,
    F_057,
    F_058,
    F_059,
    F_060,
)


@pytest.mark.parametrize("module", _VALIDATOR_MODULES, ids=lambda m: m.__name__)
def test_validator_main_passes(module: object) -> None:
    # Each validator returns 0 on success (F_022 returns 0 even if agent_core is
    # absent, per its lazy-import contract; F_060 does the same for its
    # architecture.yaml/grimp sub-check, since grimp is not installed in this
    # environment -- the dedicated "architecture drift + freshness" CI job covers
    # that check separately, with grimp installed).
    main_fn = getattr(module, "main", None) or getattr(module, "validate", None)
    assert main_fn is not None, f"No main/validate function in {module}"
    assert main_fn() == 0


class TestCiEnforces:
    """``_common.ci_enforces`` accepts either CI wiring but still catches a real regression."""

    GATE = 'mypy "tests"\nruff check "."'
    DELEGATED = "uses: ./.github/actions/run-quality-gate\n  check: make check"
    INLINE = "- run: mypy tests"
    NEITHER = "- run: echo nothing-to-see-here"

    def test_inline_spelling_passes(self) -> None:
        assert _common.ci_enforces(self.INLINE, "", inline="mypy tests", in_gate='mypy "tests"')

    def test_delegated_wiring_passes_when_the_gate_runs_the_step(self) -> None:
        assert _common.ci_enforces(self.DELEGATED, self.GATE, inline="mypy tests", in_gate='mypy "tests"')

    def test_delegated_wiring_fails_when_the_gate_drops_the_step(self) -> None:
        # The regression that matters: CI delegates, but the gate no longer type-checks.
        assert not _common.ci_enforces(self.DELEGATED, "", inline="mypy tests", in_gate='mypy "tests"')

    def test_fails_when_neither_inline_nor_delegated(self) -> None:
        assert not _common.ci_enforces(self.NEITHER, self.GATE, inline="mypy tests", in_gate='mypy "tests"')

    @pytest.mark.parametrize("token", ["run-quality-gate", "quality-gate.sh", "make check"])
    def test_every_delegation_token_is_recognised(self, token: str) -> None:
        assert _common.delegates_to_gate(f"steps:\n  - run: {token}")

    def test_unrelated_workflow_is_not_treated_as_delegating(self) -> None:
        assert not _common.delegates_to_gate(self.NEITHER)


def test_imported_validators_and_the_ci_cov_list_agree() -> None:
    """The two lists that must never drift: what this file imports, and what the
    tooling-coverage step measures.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    imported = {module.__name__ for module in _VALIDATOR_MODULES}
    workflow = (root / ".github" / "workflows" / "quality-gates.yml").read_text(encoding="utf-8")
    measured = set(re.findall(r"--cov=(F_\d+)", workflow))
    assert imported == measured, (
        "validator import list and quality-gates.yml --cov= list disagree:\n"
        f"  imported but unmeasured: {sorted(imported - measured)}\n"
        f"  measured but unimported: {sorted(measured - imported)}"
    )


def test_common_check_records_failure() -> None:
    errors: list[str] = []
    assert _common.check(True, "ok", errors) is True
    assert errors == []
    assert _common.check(False, "boom", errors) is False
    assert errors == ["boom"]


def test_common_report_exit_codes() -> None:
    import logging

    log = logging.getLogger("test")
    assert _common.report(log, "F-X", []) == 0
    assert _common.report(log, "F-X", ["a", "b"]) == 1
