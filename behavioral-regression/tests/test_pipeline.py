from __future__ import annotations

import json
import socket

import pytest

from behavioral_regression.config import BRConfig  # type: ignore[import-not-found]
from behavioral_regression.generator import PairedResponse  # type: ignore[import-not-found]
from behavioral_regression.judge import JVerdict  # type: ignore[import-not-found]
from behavioral_regression.pipeline import run_pipeline  # type: ignore[import-not-found]


def test_byte_identical_for_same_seed():
    cfg = BRConfig(n_pairs=300)
    a = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    b = json.dumps(run_pipeline(cfg, seed=7).to_dict(), sort_keys=True)
    assert a == b


def test_offline_guarantee(monkeypatch):
    # If the pipeline tried to touch the network this would raise; it must not.
    def _boom(*args, **kwargs):
        del args, kwargs
        raise AssertionError("network access attempted on the offline path")

    monkeypatch.setattr(socket, "socket", _boom)
    report = run_pipeline(BRConfig(n_pairs=120), seed=2)
    assert report.decision is not None


def test_injected_judge_is_used():
    class AlwaysRegressed:
        def judge(self, pair: PairedResponse) -> JVerdict:
            del pair
            return JVerdict(label=True, confidence=1.0)

    report = run_pipeline(BRConfig(n_pairs=80, power_min_sample=5), seed=4, judge=AlwaysRegressed())
    assert report.estimate.p_regression == 1.0


@pytest.mark.parametrize("v2_mean", [0.30, 0.45])
def test_runs_produce_a_decision(v2_mean):
    report = run_pipeline(BRConfig(n_pairs=200, v2_sycophancy_mean=v2_mean), seed=7)
    assert report.decision.value in {"ship", "hold", "escalate"}
