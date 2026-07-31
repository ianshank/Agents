"""Smoke + coverage tests for the per-feature validation scripts (F_020..F_023).

These scripts are run end-to-end by ``scripts/validate.py`` in CI, but were not
coverage-measured. Importing each module and invoking ``main()`` here both
asserts they still pass and brings them (and the shared ``_common`` helper) under
the quality-gate tooling coverage floor.
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
import F_031  # noqa: E402
import F_032  # noqa: E402
import F_033  # noqa: E402
import F_034  # noqa: E402
import F_035  # noqa: E402
import F_037  # noqa: E402
import F_039  # noqa: E402
import F_041  # noqa: E402
import F_045  # noqa: E402


@pytest.mark.parametrize(
    "module",
    [F_020, F_021, F_022, F_023, F_031, F_032, F_033, F_034, F_035, F_037, F_039, F_041, F_045],
    ids=[
        "F_020",
        "F_021",
        "F_022",
        "F_023",
        "F_031",
        "F_032",
        "F_033",
        "F_034",
        "F_035",
        "F_037",
        "F_039",
        "F_041",
        "F_045",
    ],
)
def test_validator_main_passes(module):
    # Each validator returns 0 on success (F_022 returns 0 even if agent_core is
    # absent, per its lazy-import contract).
    #
    # F_031/F_037 are here deliberately: both read .github/workflows/ and used to pin
    # inline CI command strings, so the ADR 0021 delegation (PR #64) broke them while the
    # underlying guarantees were intact. That break went unnoticed because quality-gates.yml
    # -- the only workflow running validate.py -- is path-filtered and does not fire on
    # `.github/`-only PRs. Asserting them here puts them in the *offline pytest suite*, which
    # eval-harness CI does run on workflow edits, so the same class of regression now fails
    # at a second, unfiltered layer.
    assert module.main() == 0


class TestCiEnforces:
    """``_common.ci_enforces`` accepts either CI wiring but still catches a real regression."""

    GATE = 'mypy "tests"\nruff check "."'
    DELEGATED = "uses: ./.github/actions/run-quality-gate\n  check: make check"
    INLINE = "- run: mypy tests"
    NEITHER = "- run: echo nothing-to-see-here"

    def test_inline_spelling_passes(self):
        assert _common.ci_enforces(self.INLINE, "", inline="mypy tests", in_gate='mypy "tests"')

    def test_delegated_wiring_passes_when_the_gate_runs_the_step(self):
        assert _common.ci_enforces(self.DELEGATED, self.GATE, inline="mypy tests", in_gate='mypy "tests"')

    def test_delegated_wiring_fails_when_the_gate_drops_the_step(self):
        # The regression that matters: CI delegates, but the gate no longer type-checks.
        assert not _common.ci_enforces(self.DELEGATED, "", inline="mypy tests", in_gate='mypy "tests"')

    def test_fails_when_neither_inline_nor_delegated(self):
        assert not _common.ci_enforces(self.NEITHER, self.GATE, inline="mypy tests", in_gate='mypy "tests"')

    @pytest.mark.parametrize("token", ["run-quality-gate", "quality-gate.sh", "make check"])
    def test_every_delegation_token_is_recognised(self, token):
        assert _common.delegates_to_gate(f"steps:\n  - run: {token}")

    def test_unrelated_workflow_is_not_treated_as_delegating(self):
        assert not _common.delegates_to_gate(self.NEITHER)


def test_common_check_records_failure():
    errors: list[str] = []
    assert _common.check(True, "ok", errors) is True
    assert errors == []
    assert _common.check(False, "boom", errors) is False
    assert errors == ["boom"]


def test_common_report_exit_codes():
    import logging

    log = logging.getLogger("test")
    assert _common.report(log, "F-X", []) == 0
    assert _common.report(log, "F-X", ["a", "b"]) == 1
