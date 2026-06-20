"""Property oracle for the SDLC domain: does the work product pass the tests?

Deterministic by construction: the verdict is a pure predicate over the candidate
and the instance's ``correct`` set — the abstract analogue of "the candidate code
passes the instance's test suite". A candidate outside the declared
``solution_space`` is *uninterpretable*, so the oracle abstains (indeterminate)
rather than guessing — that case belongs in the audit queue.

Determinism is a hard requirement (verification command #3): a flaky oracle would
inject the very oracle-error the κ-gate exists to catch, and a one-off κ measurement
cannot detect non-determinism. There is no I/O, randomness, or network here.
"""

from __future__ import annotations

from flow_protocol import FlowResult, OracleResult

from flow_corpus.suites.base import TaskInstance


class PropertyOracle:
    oracle_tier = "property"

    def __init__(self, oracle_id: str = "sdlc_property_v1") -> None:
        self.oracle_id = oracle_id

    def judge(self, instance: TaskInstance, result: FlowResult) -> OracleResult:
        candidate = result.output
        if not isinstance(candidate, str) or candidate not in instance.solution_space:
            verdict: bool | None = None  # uninterpretable -> abstain
        else:
            verdict = candidate in instance.correct
        return OracleResult(
            instance_id=instance.instance_id,
            verdict=verdict,
            oracle_tier="property",
            oracle_id=self.oracle_id,
        )
