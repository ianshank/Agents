"""The flow-protocol contract: the only types crossing the corpus/harness airgap.

A specimen (a flow variant) runs a task instance and emits a :class:`FlowResult`;
an oracle judges the work product and emits an :class:`OracleResult`. The harness
consumes only these types — never corpus internals — which is what makes the
airgap structural.

Design notes baked into the types:

* ``raw_confidence`` is **optional**. Outcome-only flows (and the discrimination
  canary's no-op specimen) have no meaningful self-reported confidence and must
  not be forced to fabricate one; the calibration path treats ``None`` as
  "outcome-only" rather than coercing it to a number.
* ``OracleResult.verdict`` is ``bool | None``; ``None`` means *indeterminate*
  (the oracle abstained) and must be routed to the audit queue, never fed to the
  gate as a guess.
* The per-instance ``agent_version`` keys outcomes by ``(agent_version, domain)``.
  The task instance is deliberately NOT part of the key — task variation is the
  population over which a single ``(agent_version, domain)`` is measured.

All models are frozen (immutable) so a result cannot be mutated after a flow or
oracle reports it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .version import PROTOCOL_VERSION

OracleTier = Literal["property", "differential", "metamorphic", "human_audit"]


class ConfidenceChannel(BaseModel):
    """Optional structured self-report a flow may emit alongside ``raw_confidence``.

    Used by the confidence cross-check to test whether a flow's *structured*
    confidence carries signal beyond a flow-type indicator. Kept deliberately
    open (``per_step`` + free-form ``signals``) so different flow shapes can
    populate what they have without the contract dictating internals.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    per_step: tuple[float, ...] = Field(
        default=(),
        description="Per-step confidence trace, if the flow exposes one (each in [0, 1]).",
    )
    signals: dict[str, float] = Field(
        default_factory=dict,
        description="Named scalar confidence signals (e.g. 'self_consistency').",
    )


class FlowResult(BaseModel):
    """What a specimen reports for one task instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = Field(default=PROTOCOL_VERSION)
    instance_id: str = Field(description="Identifies the task instance within a suite.")
    flow_type: str = Field(description="Specimen family, e.g. 'baseline', 'mcts', 'react'.")
    agent_version: str = Field(
        description="hash(impl + agent_config); the keying axis. Task is NOT included."
    )
    domain: str = Field(description="Task domain, e.g. 'sdlc'. The population axis.")
    output: Any = Field(
        default=None,
        description="The flow's work product an oracle judges; shape is domain-specific.",
    )
    raw_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-reported confidence in [0, 1], or None for outcome-only flows.",
    )
    confidence_channel: ConfidenceChannel | None = Field(default=None)
    seed: int | None = Field(
        default=None,
        description="Seed of a stochastic flow, recorded for reproducibility. NOT part of the key.",
    )


class OracleResult(BaseModel):
    """An oracle's judgement of one :class:`FlowResult`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    protocol_version: str = Field(default=PROTOCOL_VERSION)
    instance_id: str = Field(description="The instance this verdict is about (matches FlowResult).")
    verdict: bool | None = Field(
        default=None,
        description="True=correct, False=incorrect, None=indeterminate (abstain -> audit queue).",
    )
    oracle_tier: OracleTier = Field(description="Which oracle tier produced this verdict.")
    oracle_id: str = Field(description="Identifies the oracle (traceability + κ-validation).")

    @property
    def is_indeterminate(self) -> bool:
        return self.verdict is None
