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
import F_032  # noqa: E402
import F_033  # noqa: E402
import F_034  # noqa: E402
import F_035  # noqa: E402


@pytest.mark.parametrize(
    "module",
    [F_020, F_021, F_022, F_023, F_032, F_033, F_034, F_035],
    ids=["F_020", "F_021", "F_022", "F_023", "F_032", "F_033", "F_034", "F_035"],
)
def test_validator_main_passes(module):
    # Each validator returns 0 on success (F_022 returns 0 even if agent_core is
    # absent, per its lazy-import contract).
    assert module.main() == 0


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
