"""Labeling protocol: majority vote, escalate-on-tie, kappa floors."""

from __future__ import annotations

import pytest

from agent_core.config import ConfigError
from agent_core.golden import cohen_kappa, percent_agreement
from agent_core.labeling_protocol import (
    LabelingProtocolConfig,
    adjudicate,
    agreement_report,
)


def test_config_rejects_single_annotator() -> None:
    with pytest.raises(ConfigError, match="n_annotators"):
        LabelingProtocolConfig(n_annotators=1)


def test_adjudicate_majority_and_tie_and_empty() -> None:
    assert adjudicate([1, 1, 0]).label == 1
    assert adjudicate([0, 0, 1]).label == 0
    tie = adjudicate([1, 0])
    assert tie.label is None
    assert tie.reason == "tie:escalate"
    empty = adjudicate([])
    assert empty.label is None and empty.reason == "no_labels"


def test_adjudicate_require_third_still_escalates_on_tie() -> None:
    cfg = LabelingProtocolConfig(tie_policy="require_third")
    result = adjudicate([1, 0], cfg)
    assert result.label is None
    assert result.reason == "tie:require_third"


def test_adjudicate_rejects_non_binary() -> None:
    with pytest.raises(ValueError, match="0 or 1"):
        adjudicate([1, 2])


def test_agreement_report_reuses_golden_helpers() -> None:
    r1 = [1, 1, 0, 0]
    r2 = [1, 1, 0, 1]
    cfg = LabelingProtocolConfig(min_pairs=4, min_kappa=0.9, min_percent_agreement=0.9)
    report = agreement_report(r1, r2, cfg)
    assert report.n == 4
    assert report.kappa == cohen_kappa(r1, r2)
    assert report.percent_agreement == percent_agreement(r1, r2)
    assert report.may_accept is False
    assert "kappa" in report.failing_checks
    assert "percent_agreement" in report.failing_checks


def test_agreement_report_accepts_perfect_pairs() -> None:
    r1 = [1, 0] * 25
    r2 = list(r1)
    cfg = LabelingProtocolConfig(min_pairs=50)
    report = agreement_report(r1, r2, cfg)
    assert report.may_accept is True
    assert report.failing_checks == ()
    assert report.kappa == 1.0


def test_n_below_min_pairs_fails() -> None:
    cfg = LabelingProtocolConfig(min_pairs=10)
    report = agreement_report([1, 0], [1, 0], cfg)
    assert report.may_accept is False
    assert any(f.startswith("n<") for f in report.failing_checks)
