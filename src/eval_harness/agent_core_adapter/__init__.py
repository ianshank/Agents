"""agent-core integration adapter for the eval-harness.

Bridges the harness's LLM-judge subsystem to agent-core's deterministic
loop control, allowing :class:`~agent_core.LoopController` to orchestrate
multi-cycle evaluations with budget enforcement and convergence detection.

Claim IDs
---------
``CycleState.unresolved`` holds opaque ``str`` claim IDs.  :class:`ItemStore`
maps those IDs back to :class:`~eval_harness.core.types.EvalItem` objects.
The IDs are never rewritten or sanitised — doing so would corrupt identity
and break ``NoProgressCondition``.

Prerequisites
-------------
Install agent-core from the monorepo before importing this module::

    pip install -e "./agent-core"

All tunables live in :class:`AdapterConfig`; no literals appear in logic.
"""

from __future__ import annotations

import json
import logging
from importlib import import_module
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from eval_harness.core.interfaces import Judge
from eval_harness.core.types import EvalItem

if TYPE_CHECKING:

    class CycleState:
        cycle_index: int
        unresolved: tuple[str, ...]

    class CycleResult:
        cost: float
        new_unresolved: tuple[str, ...]
        max_conf_delta: float
        new_evidence: bool
        detail: str

        def __init__(
            self,
            *,
            cost: float,
            new_unresolved: tuple[str, ...],
            max_conf_delta: float,
            new_evidence: bool,
            detail: str = "",
        ) -> None: ...
else:
    try:
        _agent_core_protocols = import_module("agent_core.protocols")
        CycleResult = _agent_core_protocols.CycleResult
        CycleState = _agent_core_protocols.CycleState
    except ImportError as _exc:  # pragma: no cover
        raise ImportError(
            "agent-core is required for eval_harness.agent_core_adapter. "
            "Install it from the monorepo: pip install -e './agent-core'"
        ) from _exc

__all__ = [
    "AdapterConfig",
    "FixedCostEstimator",
    "HarnessJudgeRunner",
    "ItemStore",
]

log = logging.getLogger(__name__)


class AdapterConfig(BaseModel):
    """Configuration for the agent-core ↔ harness bridge.

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


class ItemStore:
    """Maps opaque claim IDs to :class:`~eval_harness.core.types.EvalItem` objects.

    Claim IDs in ``CycleState.unresolved`` are opaque strings.  This store
    is the single bridge from those IDs back to the full ``EvalItem``.
    Duplicate IDs raise :class:`ValueError` at construction time.
    """

    def __init__(self, items: list[EvalItem]) -> None:
        self._store: dict[str, EvalItem] = {}
        for item in items:
            if item.id in self._store:
                raise ValueError(f"Duplicate EvalItem ID: {item.id!r}")
            self._store[item.id] = item

    @property
    def claim_ids(self) -> tuple[str, ...]:
        """All stored IDs in insertion order — pass to ``CycleState.unresolved``."""
        return tuple(self._store.keys())

    def get(self, claim_id: str) -> EvalItem:
        try:
            return self._store[claim_id]
        except KeyError:
            raise KeyError(f"No EvalItem with ID {claim_id!r}") from None

    def __len__(self) -> int:
        return len(self._store)


class HarnessJudgeRunner:
    """Implements the agent-core ``CycleRunner`` protocol via the harness :class:`Judge`.

    Each :meth:`run` call evaluates every unresolved claim with the injected
    judge.  Claims scoring ``>= config.resolution_threshold`` are resolved and
    dropped from the next cycle's ``unresolved`` set.

    Cost per cycle: ``len(unresolved) * tokens_per_claim * per_token_rate``.

    ``max_conf_delta`` tracks the largest score change since the previous cycle.
    On the first cycle ``prev_score`` defaults to ``0.0`` so delta equals the
    raw score — this prevents a spurious convergence signal on cycle 1.

    Create a new instance per ``LoopController`` run (state is not reset between
    ``run`` calls; the controller owns the lifecycle).
    """

    def __init__(
        self,
        judge: Judge,
        item_store: ItemStore,
        config: AdapterConfig,
    ) -> None:
        self._judge = judge
        self._store = item_store
        self._config = config
        self._prev_scores: dict[str, float] = {}

    def run(self, state: CycleState) -> CycleResult:
        scores: dict[str, float] = {}
        still_unresolved: list[str] = []
        total_cost = 0.0

        for claim_id in state.unresolved:
            item = self._store.get(claim_id)
            prompt = self._config.judge_prompt_template.format(
                claim_id=claim_id,
                inputs_json=json.dumps(item.inputs, ensure_ascii=False, indent=2),
                expected=item.expected,
            )
            verdict = self._judge.evaluate(prompt, context={"claim_id": claim_id})
            score = verdict.score
            scores[claim_id] = score
            total_cost += self._config.tokens_per_claim * self._config.per_token_rate

            resolved = score >= self._config.resolution_threshold
            if not resolved:
                still_unresolved.append(claim_id)

            log.debug(
                "cycle=%d claim=%r score=%.4f resolved=%s",
                state.cycle_index,
                claim_id,
                score,
                resolved,
            )

        # prev defaults to 0.0 so first-cycle delta == score (no premature convergence)
        max_delta = max(
            (abs(s - self._prev_scores.get(cid, 0.0)) for cid, s in scores.items()),
            default=0.0,
        )
        self._prev_scores = scores

        new_evidence = len(still_unresolved) < len(state.unresolved)

        return CycleResult(
            cost=total_cost,
            new_unresolved=tuple(still_unresolved),
            max_conf_delta=max_delta,
            new_evidence=new_evidence,
        )


class FixedCostEstimator:
    """Implements the agent-core ``CostEstimator`` protocol.

    Projects the next cycle's cost as::

        len(state.unresolved) * config.tokens_per_claim * config.per_token_rate

    All constants come from :class:`AdapterConfig`; nothing is hard-coded.
    """

    def __init__(self, config: AdapterConfig) -> None:
        self._config = config

    def project(self, state: CycleState) -> float:
        return len(state.unresolved) * self._config.tokens_per_claim * self._config.per_token_rate
