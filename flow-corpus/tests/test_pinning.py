"""Two-way version-pin tests, including the forced-mismatch negative test.

The negative test is a *gate*: a wrong pin MUST raise. If it silently passed, the
skew tripwire would be dead and the airgap's version coupling unguarded.
"""

from __future__ import annotations

import pytest

import flow_corpus.pinning as pinning
from flow_corpus.pinning import PinMismatchError, check_pins, verify_pins


def test_pins_match_live_versions() -> None:
    report = verify_pins()
    assert report.ok
    assert report.protocol_expected == report.protocol_actual
    assert report.harness_expected == report.harness_actual


def test_forced_protocol_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinning, "PROTOCOL_VERSION", "9.9.9")
    with pytest.raises(PinMismatchError, match="protocol expected"):
        verify_pins()


def test_forced_harness_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinning, "_live_harness_version", lambda: "9.9.9")
    with pytest.raises(PinMismatchError, match="harness expected"):
        verify_pins()


def test_check_pins_reports_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pinning, "PROTOCOL_VERSION", "9.9.9")
    report = check_pins()  # does not raise
    assert report.ok is False
    assert report.protocol_actual == "9.9.9"
