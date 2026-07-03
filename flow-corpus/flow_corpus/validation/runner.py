"""The Phase-1 validation runner: specimen x suite -> oracle -> keyed outcomes -> reliability.

Flow of one run:
    instance -> specimen.run -> FlowResult -> oracle.judge -> OracleResult
             -> OutcomeRecord keyed by (agent_version, domain)   [determinate only]
             -> Brier reliability over confidence-bearing, determinate outcomes.

Indeterminate verdicts are counted (for the derived-cap check) but never turned into
outcomes — the gate is never fed a guess.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from agent_core.calibration import selective_risk_coverage
from agent_core.logging_util import debug_span, get_logger
from agent_core.outcome_store import OutcomeRecord
from flow_protocol import FlowResult, OracleResult

from flow_corpus.config import CorpusConfig
from flow_corpus.oracles.base import Oracle
from flow_corpus.specimens.base import Specimen
from flow_corpus.suites.base import TaskSuite

from .metrics import aurc
from .reliability import ReliabilityReport, brier_reliability

_log = get_logger("flow_corpus.validation.runner")

_MERGED_AT = "1970-01-01T00:00:00+00:00"  # corpus runs are synthetic; timestamp is fixed/inert
# Corpus outcomes are labeled by an oracle, NOT an unbiased human-audit sample. Use a
# distinct source string (never LabelSource.HUMAN_AUDIT) so that if these records ever reach
# agent_core's merge-gate store, build_domain_models / resolved() correctly exclude them from
# the authoritative auto-merge calibration.
_ORACLE_LABEL_SOURCE = "corpus_oracle"


@dataclass(frozen=True)
class RunResult:
    agent_version: str
    domain: str
    flow_results: tuple[FlowResult, ...]
    oracle_results: tuple[OracleResult, ...]
    outcome_records: tuple[OutcomeRecord, ...]
    reliability: ReliabilityReport
    aurc: float | None  # area under risk-coverage (discrimination); None if no confidences
    outcomes: tuple[int, ...]  # per determinate instance: 1 correct / 0 incorrect
    n_indeterminate: int
    n_total: int

    @property
    def indeterminate_rate(self) -> float:
        return self.n_indeterminate / self.n_total if self.n_total else 0.0

    def within_indeterminate_cap(self, cfg: CorpusConfig) -> bool:
        return self.indeterminate_rate <= cfg.max_indeterminate_rate


def run_suite(
    specimen: Specimen,
    suite: TaskSuite,
    oracle: Oracle,
    cfg: CorpusConfig,
    *,
    seed: int = 0,
) -> RunResult:
    """Run *specimen* across *suite*, judge with *oracle*, and key outcomes.

    Stochastic specimens draw from a per-run ``random.Random(seed)`` so a run is
    byte-reproducible. The run seed is stamped onto each FlowResult for provenance;
    it is deliberately NOT part of the version key (which is impl + agent_config only).
    """
    rng = random.Random(seed)
    flow_results: list[FlowResult] = []
    oracle_results: list[OracleResult] = []
    records: list[OutcomeRecord] = []
    confidences: list[float] = []
    conf_outcomes: list[int] = []
    outcomes: list[int] = []
    n_indeterminate = 0

    agent_version = specimen.agent_version
    with debug_span(
        _log,
        "run_suite",
        flow_type=specimen.flow_type,
        agent_version=agent_version,
        domain=suite.domain,
        n_instances=len(suite.instances),
        seed=seed,
    ):
        for instance in suite.instances:
            fr = specimen.run(instance, rng).model_copy(update={"seed": seed})
            verdict = oracle.judge(instance, fr)
            flow_results.append(fr)
            oracle_results.append(verdict)

            if verdict.verdict is None:
                n_indeterminate += 1
                continue  # never synthesise an outcome from an abstention

            outcome = 1 if verdict.verdict else 0
            outcomes.append(outcome)
            if fr.raw_confidence is not None:
                confidences.append(fr.raw_confidence)
                conf_outcomes.append(outcome)
                records.append(
                    OutcomeRecord(
                        change_id=instance.instance_id,
                        domain=instance.domain,
                        raw_confidence=fr.raw_confidence,
                        merged_at=_MERGED_AT,
                        label=verdict.verdict,
                        label_source=_ORACLE_LABEL_SOURCE,
                        labeled_at=_MERGED_AT,
                        agent_version=agent_version,
                    )
                )

        reliability = brier_reliability(confidences, conf_outcomes, cfg)
        # Discrimination: area under the risk-coverage curve over confidence-bearing
        # outcomes. Undefined (None) when the flow reports no confidences.
        aurc_value = (
            aurc(selective_risk_coverage(confidences, conf_outcomes)) if confidences else None
        )

    n_total = len(suite.instances)
    indeterminate_rate = n_indeterminate / n_total if n_total else 0.0
    if indeterminate_rate > cfg.max_indeterminate_rate:
        _log.warning(
            "indeterminate rate %.4f exceeds derived cap %.4f flow_type=%s domain=%s "
            "n_indeterminate=%d n_total=%d (oracle abstentions exceed the audit budget)",
            indeterminate_rate,
            cfg.max_indeterminate_rate,
            specimen.flow_type,
            suite.domain,
            n_indeterminate,
            n_total,
        )
    _log.info(
        "run_suite complete flow_type=%s agent_version=%s domain=%s "
        "n_total=%d n_indeterminate=%d indeterminate_rate=%.4f reliability=%s aurc=%s",
        specimen.flow_type,
        agent_version,
        suite.domain,
        n_total,
        n_indeterminate,
        indeterminate_rate,
        reliability.reliability,
        aurc_value,
    )

    return RunResult(
        agent_version=agent_version,
        domain=suite.domain,
        flow_results=tuple(flow_results),
        oracle_results=tuple(oracle_results),
        outcome_records=tuple(records),
        reliability=reliability,
        aurc=aurc_value,
        outcomes=tuple(outcomes),
        n_indeterminate=n_indeterminate,
        n_total=len(suite.instances),
    )
