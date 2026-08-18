"""Tests for eval_harness.agent_core_adapter.

All tests use deterministic doubles — no network, no real LLM.
agent-core is imported via pytest.importorskip so the harness CI
can still run this file when agent-core IS installed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

agent_core = pytest.importorskip("agent_core")

if TYPE_CHECKING:
    from agent_core import CycleState

from eval_harness.agent_core_adapter import (  # noqa: E402
    AdapterConfig,
    FixedCostEstimator,
    HarnessJudgeRunner,
    ItemStore,
)
from eval_harness.core.interfaces import Judge  # noqa: E402
from eval_harness.core.types import EvalItem, JudgeVerdict  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ITEMS_3 = [
    EvalItem(id="c1", inputs={"q": "What is 2+2?"}, expected=4),
    EvalItem(id="c2", inputs={"q": "Capital of France?"}, expected="Paris"),
    EvalItem(id="c3", inputs={"q": "Is Python typed?"}, expected=True),
]


def _store(items: list[EvalItem] | None = None) -> ItemStore:
    return ItemStore(items if items is not None else ITEMS_3)


def _config(**kwargs: Any) -> AdapterConfig:
    return AdapterConfig(**kwargs)


class _FixedJudge(Judge):
    """Returns a fixed score for every claim."""

    def __init__(self, score: float) -> None:
        self._score = score

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        return JudgeVerdict(score=self._score, reasoning="fixed")


class _PerClaimJudge(Judge):
    """Returns a different score depending on the claim_id in context."""

    def __init__(self, scores: dict[str, float]) -> None:
        self._scores = scores

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        cid = (context or {}).get("claim_id", "")
        return JudgeVerdict(score=self._scores.get(cid, 0.0))


# ---------------------------------------------------------------------------
# ItemStore
# ---------------------------------------------------------------------------


class TestItemStore:
    def test_get_returns_correct_item(self) -> None:
        store = _store()
        assert store.get("c1") is ITEMS_3[0]

    def test_get_missing_raises_key_error(self) -> None:
        store = _store()
        with pytest.raises(KeyError, match="no_such"):
            store.get("no_such")

    def test_rejects_duplicate_ids(self) -> None:
        dup = [EvalItem(id="x", inputs={}, expected=None), EvalItem(id="x", inputs={}, expected=1)]
        with pytest.raises(ValueError, match="Duplicate"):
            ItemStore(dup)

    def test_claim_ids_preserves_insertion_order(self) -> None:
        store = _store()
        assert store.claim_ids == ("c1", "c2", "c3")

    def test_len_equals_number_of_items(self) -> None:
        assert len(_store()) == 3

    def test_empty_store(self) -> None:
        store = ItemStore([])
        assert store.claim_ids == ()
        assert len(store) == 0


# ---------------------------------------------------------------------------
# AdapterConfig
# ---------------------------------------------------------------------------


class TestAdapterConfig:
    def test_defaults_are_valid(self) -> None:
        cfg = AdapterConfig()
        assert 0.0 <= cfg.resolution_threshold <= 1.0
        assert cfg.tokens_per_claim >= 1
        assert cfg.per_token_rate >= 0.0
        assert "{claim_id}" in cfg.judge_prompt_template

    def test_rejects_threshold_above_one(self) -> None:
        with pytest.raises(ValidationError):
            AdapterConfig(resolution_threshold=1.1)

    def test_rejects_threshold_below_zero(self) -> None:
        with pytest.raises(ValidationError):
            AdapterConfig(resolution_threshold=-0.1)

    def test_rejects_zero_tokens_per_claim(self) -> None:
        with pytest.raises(ValidationError):
            AdapterConfig(tokens_per_claim=0)

    def test_rejects_negative_per_token_rate(self) -> None:
        with pytest.raises(ValidationError):
            AdapterConfig(per_token_rate=-1.0)

    def test_config_is_frozen(self) -> None:
        cfg = AdapterConfig()
        with pytest.raises(ValidationError):
            cfg.tokens_per_claim = 9999  # type: ignore[misc]

    def test_custom_template_is_stored(self) -> None:
        tmpl = "Evaluate {claim_id}: {inputs_json} / {expected}"
        cfg = AdapterConfig(judge_prompt_template=tmpl)
        assert cfg.judge_prompt_template == tmpl


# ---------------------------------------------------------------------------
# HarnessJudgeRunner
# ---------------------------------------------------------------------------


class TestHarnessJudgeRunner:
    def _runner(
        self,
        judge: Judge,
        *,
        threshold: float = 0.8,
        tokens: int = 100,
        rate: float = 0.01,
    ) -> HarnessJudgeRunner:
        cfg = _config(resolution_threshold=threshold, tokens_per_claim=tokens, per_token_rate=rate)
        return HarnessJudgeRunner(judge, _store(), cfg)

    def _state(self, *ids: str) -> CycleState:
        return agent_core.CycleState(cycle_index=1, unresolved=tuple(ids))

    def test_resolves_all_claims_above_threshold(self) -> None:
        runner = self._runner(_FixedJudge(0.9))
        result = runner.run(self._state("c1", "c2", "c3"))
        assert result.new_unresolved == ()

    def test_keeps_claims_below_threshold_unresolved(self) -> None:
        runner = self._runner(_FixedJudge(0.3))
        result = runner.run(self._state("c1", "c2", "c3"))
        assert set(result.new_unresolved) == {"c1", "c2", "c3"}

    def test_mixed_threshold(self) -> None:
        judge = _PerClaimJudge({"c1": 0.9, "c2": 0.4, "c3": 0.95})
        runner = self._runner(judge)
        result = runner.run(self._state("c1", "c2", "c3"))
        assert set(result.new_unresolved) == {"c2"}

    def test_cost_equals_n_claims_times_rate(self) -> None:
        runner = self._runner(_FixedJudge(0.5), tokens=1_000, rate=0.001)
        result = runner.run(self._state("c1", "c2", "c3"))
        expected_cost = 3 * 1_000 * 0.001
        assert math.isclose(result.cost, expected_cost, rel_tol=1e-9)

    def test_empty_unresolved_returns_zero_cost(self) -> None:
        runner = self._runner(_FixedJudge(0.9))
        result = runner.run(self._state())
        assert result.cost == 0.0
        assert result.new_unresolved == ()

    def test_first_cycle_delta_equals_score(self) -> None:
        # prev defaults to 0.0 → delta == |score - 0| == score
        runner = self._runner(_FixedJudge(0.6))
        result = runner.run(self._state("c1"))
        assert math.isclose(result.max_conf_delta, 0.6, rel_tol=1e-9)

    def test_second_cycle_delta_is_score_change(self) -> None:
        judge = _PerClaimJudge({"c1": 0.4})
        runner = self._runner(judge)
        runner.run(self._state("c1"))  # cycle 1: prev=0.0, score=0.4 → delta=0.4

        judge._scores["c1"] = 0.7  # cycle 2: score=0.7, prev=0.4 → delta=0.3
        state2 = agent_core.CycleState(cycle_index=2, unresolved=("c1",))
        result2 = runner.run(state2)
        assert math.isclose(result2.max_conf_delta, 0.3, rel_tol=1e-9)

    def test_new_evidence_true_when_claims_resolved(self) -> None:
        runner = self._runner(_FixedJudge(0.9))
        result = runner.run(self._state("c1", "c2"))
        assert result.new_evidence is True

    def test_new_evidence_false_when_nothing_resolved(self) -> None:
        runner = self._runner(_FixedJudge(0.1))
        result = runner.run(self._state("c1", "c2"))
        assert result.new_evidence is False

    def test_prompt_contains_claim_id_and_inputs(self) -> None:
        recorded: list[str] = []

        class _RecordingJudge(Judge):
            def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
                recorded.append(prompt)
                return JudgeVerdict(score=0.9)

        cfg = _config()
        runner = HarnessJudgeRunner(_RecordingJudge(), _store(), cfg)
        runner.run(self._state("c1"))
        assert "c1" in recorded[0]
        assert "What is 2+2?" in recorded[0]

    def test_context_contains_claim_id(self) -> None:
        contexts: list[dict | None] = []

        class _ContextRecordingJudge(Judge):
            def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
                contexts.append(context)
                return JudgeVerdict(score=0.9)

        cfg = _config()
        runner = HarnessJudgeRunner(_ContextRecordingJudge(), _store(), cfg)
        runner.run(self._state("c2"))
        assert contexts[0] == {"claim_id": "c2"}

    def test_protocol_conformance(self) -> None:
        runner = self._runner(_FixedJudge(0.9))
        assert isinstance(runner, agent_core.CycleRunner)


# ---------------------------------------------------------------------------
# FixedCostEstimator
# ---------------------------------------------------------------------------


class TestFixedCostEstimator:
    def _est(self, tokens: int = 2_000, rate: float = 1e-5) -> FixedCostEstimator:
        return FixedCostEstimator(_config(tokens_per_claim=tokens, per_token_rate=rate))

    def _state(self, *ids: str) -> CycleState:
        return agent_core.CycleState(unresolved=tuple(ids))

    def test_projects_n_unresolved_times_rate(self) -> None:
        est = self._est(tokens=500, rate=0.002)
        state = self._state("a", "b", "c")
        expected = 3 * 500 * 0.002
        assert math.isclose(est.project(state), expected, rel_tol=1e-9)

    def test_empty_state_projects_zero(self) -> None:
        est = self._est()
        assert est.project(self._state()) == 0.0

    def test_single_claim(self) -> None:
        est = self._est(tokens=1_000, rate=0.01)
        assert math.isclose(est.project(self._state("x")), 10.0, rel_tol=1e-9)

    def test_protocol_conformance(self) -> None:
        est = self._est()
        assert isinstance(est, agent_core.CostEstimator)


# ---------------------------------------------------------------------------
# Integration: LoopController wired through adapter
# ---------------------------------------------------------------------------


class TestLoopControllerIntegration:
    """Wires HarnessJudgeRunner + FixedCostEstimator into agent-core's LoopController.

    Uses convergence_epsilon=1.0 so the loop stops after the first cycle where
    all claims are resolved (SUCCESS) — deterministic without real LLM.
    """

    def test_loop_controller_converges_when_all_claims_resolved(self) -> None:
        # All scores above threshold → resolves in one cycle
        adapter_cfg = AdapterConfig(
            resolution_threshold=0.5,
            tokens_per_claim=10,
            per_token_rate=0.01,
        )
        store = ItemStore(
            [
                EvalItem(id="q1", inputs={"text": "hello"}, expected=1),
                EvalItem(id="q2", inputs={"text": "world"}, expected=1),
            ]
        )
        judge = _FixedJudge(0.9)
        runner = HarnessJudgeRunner(judge, store, adapter_cfg)
        estimator = FixedCostEstimator(adapter_cfg)

        framework_cfg = agent_core.FrameworkConfig.from_dict(
            {
                "loop": {"max_cycles": 10, "convergence_epsilon": 1.0},
                "budget": {"cap_units": 10_000.0},
            }
        )
        ledger = agent_core.BudgetLedger(framework_cfg)
        controller = agent_core.LoopController(framework_cfg, ledger, runner, estimator)

        initial_state = agent_core.CycleState(unresolved=("q1", "q2"))
        result = controller.run(initial_state)

        assert result.reason is agent_core.StopReason.SUCCESS
        assert result.cycles_completed >= 1
        assert result.spent > 0.0

    def test_loop_controller_stalls_when_no_claims_resolve(self) -> None:
        # Score stays below threshold → unresolved set unchanged from initial state → STALL
        # NoProgressCondition fires after cycle 1 (prev_unresolved == new_unresolved).
        adapter_cfg = AdapterConfig(
            resolution_threshold=0.95,
            tokens_per_claim=5,
            per_token_rate=0.001,
        )
        store = ItemStore([EvalItem(id="q1", inputs={"x": "y"}, expected=0)])
        judge = _FixedJudge(0.3)  # 0.3 < 0.95 → never resolves → unresolved set unchanged
        runner = HarnessJudgeRunner(judge, store, adapter_cfg)
        estimator = FixedCostEstimator(adapter_cfg)

        framework_cfg = agent_core.FrameworkConfig.from_dict(
            {
                "loop": {"max_cycles": 10},
                "budget": {"cap_units": 10_000.0},
            }
        )
        ledger = agent_core.BudgetLedger(framework_cfg)
        controller = agent_core.LoopController(framework_cfg, ledger, runner, estimator)

        initial_state = agent_core.CycleState(unresolved=("q1",))
        result = controller.run(initial_state)

        # NoProgressCondition fires because unresolved set == initial unresolved set
        assert result.reason is agent_core.StopReason.STALL
        assert result.cycles_completed == 1

    def test_item_store_claim_ids_wire_directly_to_cycle_state(self) -> None:
        items = [EvalItem(id=f"item-{i}", inputs={"i": i}, expected=i) for i in range(5)]
        store = ItemStore(items)
        assert store.claim_ids == tuple(f"item-{i}" for i in range(5))

        # Directly usable as initial CycleState.unresolved
        state = agent_core.CycleState(unresolved=store.claim_ids)
        assert len(state.unresolved) == 5


# ---------------------------------------------------------------------------
# require_report_to_gate (extend-judge-calibration Group 4)
# ---------------------------------------------------------------------------


def _calibration_report(**overrides: Any):
    from agent_core import (
        JudgeCalibrationReport,
        OrderProbeResult,
        VerbosityProbeResult,
    )

    order_flip = overrides.pop(
        "order_flip",
        OrderProbeResult(n=10, flips=0, flip_rate=0.0, ci_low=0.0, ci_high=0.1, passes=True),
    )
    verbosity = overrides.pop(
        "verbosity",
        VerbosityProbeResult(
            n=10,
            ties=0,
            concise_wins=5,
            expanded_wins=5,
            expanded_win_rate=0.5,
            preference_delta=0.0,
            ci_low=0.2,
            ci_high=0.8,
            passes=True,
        ),
    )
    defaults: dict[str, Any] = dict(
        schema_version="1.0.0",
        judge_id="j1",
        artifact_id="run-123",
        n_total=100,
        n_codeterminate=90,
        percent_agreement=0.9,
        kappa=0.85,
        directional_only=False,
        agreement_may_gate=True,
        order_flip=order_flip,
        verbosity=verbosity,
        self_preference=None,
        canary_pass_rate=1.0,
    )
    defaults.update(overrides)
    return JudgeCalibrationReport(**defaults)


class TestRequireReportToGate:
    """spec.md 'Uncalibrated judges cannot gate releases' — enforced against a real
    ``agent_core.JudgeCalibrationReport``, not just the config-level artifact-ID
    presence check in ``eval_harness.gating.require_calibration_for_judge_gating``."""

    def test_raises_when_the_artifact_id_does_not_match(self) -> None:
        from eval_harness.agent_core_adapter import require_report_to_gate

        report = _calibration_report(artifact_id="run-123")
        with pytest.raises(ValueError, match="does not match"):
            require_report_to_gate(report, "run-999")

    def test_raises_when_the_report_does_not_authorise_gating(self) -> None:
        from agent_core import OrderProbeResult

        from eval_harness.agent_core_adapter import require_report_to_gate

        failing_order = OrderProbeResult(n=10, flips=8, flip_rate=0.8, ci_low=0.5, ci_high=0.9, passes=False)
        report = _calibration_report(artifact_id="run-123", order_flip=failing_order)
        with pytest.raises(ValueError, match="order_flip"):
            require_report_to_gate(report, "run-123")

    def test_passes_when_the_report_authorises_gating_under_the_matching_id(self) -> None:
        from eval_harness.agent_core_adapter import require_report_to_gate

        report = _calibration_report(artifact_id="run-123")
        require_report_to_gate(report, "run-123")  # must not raise
