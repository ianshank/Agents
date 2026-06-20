"""Logging/observability tests: the runner emits a structured summary + debug span."""

from __future__ import annotations

import logging

from flow_corpus.config import CorpusConfig
from flow_corpus.oracles import PropertyOracle
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import BaselineSpecimen
from flow_corpus.suites.sdlc import build_sdlc_suite
from flow_corpus.validation import run_suite

CFG = CorpusConfig(declared_n_per_domain=60, power_min_sample=1)
SUITE = build_sdlc_suite(CFG, seed=11)


def test_run_suite_emits_info_summary(caplog) -> None:
    spec = BaselineSpecimen(MockPolicy(skill=0.75, confidence_quality=1.0))
    with caplog.at_level(logging.INFO, logger="flow_corpus.validation.runner"):
        run_suite(spec, SUITE, PropertyOracle(), CFG, seed=3)
    records = [r for r in caplog.records if r.name == "flow_corpus.validation.runner"]
    assert any("run_suite complete" in r.getMessage() for r in records)
    msg = next(r.getMessage() for r in records if "run_suite complete" in r.getMessage())
    assert f"agent_version={spec.agent_version}" in msg
    assert "domain=sdlc" in msg
    assert "reliability=" in msg and "aurc=" in msg


def test_run_suite_emits_debug_span(caplog) -> None:
    spec = BaselineSpecimen(MockPolicy())
    with caplog.at_level(logging.DEBUG, logger="flow_corpus.validation.runner"):
        run_suite(spec, SUITE, PropertyOracle(), CFG, seed=0)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("ENTER run_suite") for m in msgs)
    assert any(m.startswith("EXIT  run_suite") and "elapsed_ms=" in m for m in msgs)
