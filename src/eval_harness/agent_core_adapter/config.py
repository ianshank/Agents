"""Configuration for the agent-core <-> harness bridge.

Split from ``agent_core_adapter/__init__.py`` purely to stay under the
500-line file budget (see ``calibration.py``'s module docstring for the
sibling-module precedent this package already established).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AdapterConfig(BaseModel):
    """Configuration for the agent-core <-> harness bridge.

    Every tunable is a validated field; no literals appear in logic.
    """

    model_config = ConfigDict(frozen=True)

    resolution_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Judge score >= this value marks a claim as resolved.",
    )
    tokens_per_claim: int = Field(
        default=2_000,
        ge=1,
        description="Estimated token count per judge call (for cost accounting).",
    )
    per_token_rate: float = Field(
        default=1e-5,
        ge=0.0,
        description="Cost per token in agent-core budget units.",
    )
    judge_prompt_template: str = Field(
        default=("Evaluate the following claim.\n\nClaim ID: {claim_id}\nInputs:\n{inputs_json}\nExpected: {expected}"),
        description=("Template for judge prompts. Available variables: {claim_id}, {inputs_json}, {expected}."),
    )
