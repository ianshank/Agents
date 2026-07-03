from __future__ import annotations

import json
import logging
import socket

import pytest

from behavioral_regression.config import BRConfig
from behavioral_regression.generator import PairedResponse
from behavioral_regression.judge import JVerdict
from behavioral_regression.pipeline import run_pipeline


def test_byte_identical_for_same_seed():
    cfg = BRConfig(n_pairs=300)
    a = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    b = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    assert a == b


def test_offline_guarantee(monkeypatch):
    # If the pipeline tried to touch the network this would raise; it must not.
    def _boom(*a, **k):
        raise AssertionError("network access attempted on the offline path")

    monkeypatch.setattr(socket, "socket", _boom)
    report = run_pipeline(BRConfig(n_pairs=120), seed=2)
    assert report.decision is not None


def test_injected_judge_is_used():
    class AlwaysRegressed:
        def judge(self, pair: PairedResponse) -> JVerdict:
            return JVerdict(label=True, confidence=1.0)

    report = run_pipeline(BRConfig(n_pairs=80, power_min_sample=5), seed=4, judge=AlwaysRegressed())
    assert report.estimate.p_regression == 1.0


@pytest.mark.parametrize("v2_mean", [0.30, 0.45])
def test_runs_produce_a_decision(v2_mean):
    report = run_pipeline(BRConfig(n_pairs=200, v2_sycophancy_mean=v2_mean), seed=7)
    assert report.decision.value in {"ship", "hold", "escalate"}


def test_pipeline_logs_stage_boundaries_and_decision(caplog):
    cfg = BRConfig(n_pairs=120)
    with caplog.at_level(logging.INFO, logger="behavioral_regression"):
        report = run_pipeline(cfg, seed=2)
    assert "generate: 120 response pairs (seed=2)" in caplog.text
    assert "judge: 120 verdicts" in caplog.text
    assert "validate: kappa=" in caplog.text
    assert f"pipeline complete: decision={report.decision.value} (seed=2)" in caplog.text
