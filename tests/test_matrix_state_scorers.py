"""Test Matrix: the ``state_transition`` and ``policy_violation`` scorers
(F-060, ``add-stateful-outcome-evaluation``).

Split into its own file rather than grown inside ``test_matrix_eval_tools.py``
— the cell-map extractor globs ``test_matrix_*.py``, so a per-feature file is
a first-class citizen (precedent: ``test_matrix_panel_judge.py``,
``test_matrix_state_adapters.py``, both from this same session).

Run: pytest tests/test_matrix_state_scorers.py -v --tb=short
"""

from __future__ import annotations

import pytest

from eval_harness.core.types import EvalItem, RunContext, ScoreResult, StateEvaluation, TargetOutput
from eval_harness.plugins import SCORERS, bootstrap

bootstrap()

_ITEM = EvalItem(id="i1", inputs={}, expected=None)
_OUTPUT = TargetOutput(output="done")


def _ctx_with(evaluation: object | None) -> RunContext:
    extra = {"state_evaluation": evaluation} if evaluation is not None else {}
    return RunContext(config=None, extra=extra)


class TestStateTransitionScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("state_transition",)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_goal_reached(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True)))
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_goal_not_reached(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=False)))
        assert r.value == 0.0 and r.passed is False

    def test_m1_correctness_carries_the_adapter_reasoning_as_comment(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=False, reasoning="balance mismatch")))
        assert r.comment == "balance mismatch"

    def test_m1_correctness_ignores_policy_violated_entirely(self) -> None:
        """The two scorers are independent axes -- this one never reads policy_violated."""
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True, policy_violated=True)))
        assert r.passed is True

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_no_evaluation_present_abstains(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(None))
        assert r.passed is None

    def test_m2_edge_no_state_adapter_configured_at_all(self) -> None:
        """ctx.extra is empty entirely, not just missing this one key -- the normal
        shape for a run with no state_adapter configured."""
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, RunContext(config=None))
        assert r.passed is None

    def test_m2_edge_empty_reasoning_yields_no_comment(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True)))
        assert r.comment is None

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True)))
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    def test_m3_type_safety_ignores_a_malformed_extra_value(self) -> None:
        """ctx.extra["state_evaluation"] holding something other than a
        StateEvaluation (a stale/wrong value) must not crash the scorer."""
        s = SCORERS.create("state_transition", {"name": "st"})
        r = s.score(_ITEM, _OUTPUT, RunContext(config=None, extra={"state_evaluation": "not-an-evaluation"}))
        assert r.passed is None

    # -------------------------------------------------------------- M5: determinism

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("state_transition", {"name": "st"})
        ctx = _ctx_with(StateEvaluation(goal_reached=True, reasoning="ok"))
        results = [s.score(_ITEM, _OUTPUT, ctx) for _ in range(10)]
        assert all(
            (r.value, r.passed, r.comment) == (results[0].value, results[0].passed, results[0].comment) for r in results
        )

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_unknown_param_rejected(self) -> None:
        with pytest.raises(TypeError):
            SCORERS.create("state_transition", {"name": "st", "not_a_param": 1})


class TestPolicyViolationScorer:
    MATRIX_KIND = "scorer"
    MATRIX_COMPONENTS = ("policy_violation",)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_no_violation(self) -> None:
        s = SCORERS.create("policy_violation", {"name": "pv"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True, policy_violated=False)))
        assert r.value == 1.0 and r.passed is True

    def test_m1_correctness_violation(self) -> None:
        s = SCORERS.create("policy_violation", {"name": "pv"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True, policy_violated=True)))
        assert r.value == 0.0 and r.passed is False

    def test_m1_correctness_fails_independently_of_goal_success(self) -> None:
        """The exact scenario tasks.md names: goal reached via a forbidden mutation
        still fails this scorer, regardless of state_transition's own verdict."""
        s = SCORERS.create("policy_violation", {"name": "pv"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True, policy_violated=True)))
        assert r.passed is False  # goal_reached=True does not rescue this verdict

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_no_evaluation_present_abstains(self) -> None:
        s = SCORERS.create("policy_violation", {"name": "pv"})
        assert s.score(_ITEM, _OUTPUT, _ctx_with(None)).passed is None

    def test_m2_edge_default_policy_violated_is_false(self) -> None:
        """StateEvaluation's own default -- an adapter that never mentions policy
        at all reads as 'no violation', not an abstention."""
        s = SCORERS.create("policy_violation", {"name": "pv"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True)))
        assert r.passed is True

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        s = SCORERS.create("policy_violation", {"name": "pv"})
        r = s.score(_ITEM, _OUTPUT, _ctx_with(StateEvaluation(goal_reached=True)))
        assert isinstance(r, ScoreResult)
        assert isinstance(r.value, float)
        assert isinstance(r.passed, bool)

    # -------------------------------------------------------------- M5: determinism

    def test_m5_determinism(self) -> None:
        s = SCORERS.create("policy_violation", {"name": "pv"})
        ctx = _ctx_with(StateEvaluation(goal_reached=True, policy_violated=True, reasoning="wrote /etc/locked"))
        results = [s.score(_ITEM, _OUTPUT, ctx) for _ in range(10)]
        assert all(
            (r.value, r.passed, r.comment) == (results[0].value, results[0].passed, results[0].comment) for r in results
        )

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_unknown_param_rejected(self) -> None:
        with pytest.raises(TypeError):
            SCORERS.create("policy_violation", {"name": "pv", "not_a_param": 1})
