"""Logging/observability tests: structured summaries, debug spans, degrade-path warnings."""

from __future__ import annotations

import logging
import random

import pytest

from flow_corpus.config import CorpusConfig
from flow_corpus.crosscheck import CrossCheckRow, confidence_cross_check
from flow_corpus.holdout import HoldoutManager, RotationManager, Sample
from flow_corpus.oracles import PropertyOracle
from flow_corpus.policy import MockPolicy
from flow_corpus.specimens import BaselineSpecimen
from flow_corpus.specimens.base import SpecimenBase
from flow_corpus.suites.sdlc import build_sdlc_suite
from flow_corpus.validation import run_suite

CFG = CorpusConfig(declared_n_per_domain=60, power_min_sample=1)
SUITE = build_sdlc_suite(CFG, seed=11)


def _samples(n: int, prefix: str) -> list[Sample]:
    return [
        Sample(instance_id=f"{prefix}{i}", confidence=(i % 10) / 10.0, outcome=i % 2)
        for i in range(n)
    ]


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


def test_run_suite_warns_when_indeterminate_cap_exceeded(caplog) -> None:
    class _MalformedSpecimen(SpecimenBase):
        flow_type = "malformed"
        impl_version = "1"

        def run(self, instance, rng: random.Random):
            # Output outside the solution space -> the oracle abstains on every instance.
            return self._result(instance, "not_a_candidate", confidence=0.5, seed=None)

    spec = _MalformedSpecimen(policy=MockPolicy())
    with caplog.at_level(logging.WARNING, logger="flow_corpus.validation.runner"):
        run_suite(spec, SUITE, PropertyOracle(), CFG, seed=0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("exceeds derived cap" in r.getMessage() for r in warnings)
    msg = next(r.getMessage() for r in warnings if "exceeds derived cap" in r.getMessage())
    assert "flow_type=malformed" in msg and "domain=sdlc" in msg


def test_run_suite_no_warning_within_indeterminate_cap(caplog) -> None:
    # The property oracle interprets every well-formed candidate -> 0 indeterminates.
    spec = BaselineSpecimen(MockPolicy(0.7))
    with caplog.at_level(logging.WARNING, logger="flow_corpus.validation.runner"):
        run_suite(spec, SUITE, PropertyOracle(), CFG, seed=1)
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_holdout_evaluate_emits_info_verdict(caplog) -> None:
    sbt = {"baseline": _samples(30, "b"), "react": _samples(30, "r")}
    with caplog.at_level(logging.INFO, logger="flow_corpus.holdout.manager"):
        HoldoutManager(CFG, seed=7).evaluate(sbt, held_out_type="react")
    msgs = [r.getMessage() for r in caplog.records if r.name == "flow_corpus.holdout.manager"]
    assert any("holdout evaluated" in m for m in msgs)
    msg = next(m for m in msgs if "holdout evaluated" in m)
    assert "held_out_type=react" in msg and "extrapolation_fraction=" in msg


def test_holdout_evaluate_warns_when_extrapolation_unavailable(caplog) -> None:
    # Empty held-out partition -> the seen-support caveat cannot be computed.
    sbt: dict[str, list[Sample]] = {"baseline": _samples(30, "b"), "react": []}
    with caplog.at_level(logging.WARNING, logger="flow_corpus.holdout.manager"):
        report = HoldoutManager(CFG, seed=7).evaluate(sbt, held_out_type="react")
    assert report.seen_support is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("extrapolation caveat unavailable" in r.getMessage() for r in warnings)
    msg = next(m.getMessage() for m in warnings if "extrapolation caveat" in m.getMessage())
    assert "n_held=0" in msg


def test_rotation_emits_info_summary(caplog) -> None:
    sbt = {"baseline": _samples(40, "b"), "react": _samples(40, "r")}
    with caplog.at_level(logging.INFO, logger="flow_corpus.holdout.rotation"):
        RotationManager(CFG).rotate(sbt, held_out_type="react", k_folds=3, base_seed=0)
    msgs = [r.getMessage() for r in caplog.records if r.name == "flow_corpus.holdout.rotation"]
    assert any("rotation complete" in m for m in msgs)
    msg = next(m for m in msgs if "rotation complete" in m)
    assert "held_out_type=react" in msg and "spread=" in msg and "stable=" in msg


def test_rotation_warns_on_degenerate_fold_and_errors_when_all_degenerate(caplog) -> None:
    # No seen samples at all -> every fold is degenerate (WARNING each), then ERROR + raise.
    with (
        caplog.at_level(logging.WARNING, logger="flow_corpus.holdout.rotation"),
        pytest.raises(ValueError, match="no fold produced"),
    ):
        RotationManager(CFG).rotate({"react": []}, held_out_type="react", k_folds=2)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no measurable instance-holdout reliability" in r.getMessage() for r in warnings)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("no fold produced" in r.getMessage() for r in errors)


def test_crosscheck_emits_info_verdict(caplog) -> None:
    rng = random.Random(0)
    rows = []
    for i in range(200):
        p = rng.random()
        rows.append(
            CrossCheckRow(
                flow_type="baseline" if i % 2 == 0 else "mcts",
                instance_id=f"i{i}",
                confidence=p,
                outcome=1 if rng.random() < p else 0,
            )
        )
    cfg = CorpusConfig(power_min_sample=40)
    with caplog.at_level(logging.INFO, logger="flow_corpus.crosscheck.confidence"):
        confidence_cross_check(rows, cfg, seed=2, n_resamples=100)
    msgs = [r.getMessage() for r in caplog.records if r.name == "flow_corpus.crosscheck.confidence"]
    assert any("confidence cross-check auroc_confidence=" in m for m in msgs)
    msg = next(m for m in msgs if "auroc_confidence=" in m)
    assert "adds_signal=" in msg and "excludes_zero=" in msg


def test_crosscheck_warns_on_degenerate_measure_partition(caplog) -> None:
    # Single-class outcomes -> AUROC undefined -> degrade to directional-only with a WARNING.
    rows = [
        CrossCheckRow(flow_type="baseline", instance_id=f"i{i}", confidence=0.6, outcome=1)
        for i in range(40)
    ]
    with caplog.at_level(logging.WARNING, logger="flow_corpus.crosscheck.confidence"):
        report = confidence_cross_check(rows, CorpusConfig(power_min_sample=40), seed=2)
    assert report.directional_only is True
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("degenerate measure partition" in r.getMessage() for r in warnings)
