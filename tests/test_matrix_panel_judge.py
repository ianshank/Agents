"""Test Matrix: the ``panel`` judge (F-059, ``add-panel-judge``).

Split into its own file rather than grown inside ``test_matrix_eval_tools.py`` --
the cell-map extractor globs ``test_matrix_*.py``, so a per-feature file is a
first-class citizen, not a workaround (see ``tests/_matrix_coverage.py``'s own
"future split" note). ``REQUIRED_DIMS["judge"]`` is ``{1, 2, 3, 6}`` (M5 excluded
there: "verdict determinism is the provider's") -- that exclusion does not hold
for ``panel``, whose aggregation/quorum/abstention logic is repo-owned, not a
provider sampler, so this class voluntarily carries M5 too (mirrors
``TestMockJudge``'s own precedent: mock's determinism is also repo-owned logic).

Run: pytest tests/test_matrix_panel_judge.py -v --tb=short
"""

from __future__ import annotations

import pytest

from eval_harness.core.interfaces import Judge
from eval_harness.core.types import JudgeVerdict
from eval_harness.plugins import JUDGES, bootstrap

bootstrap()


def _mock_member(score: float) -> dict:
    return {"type": "mock", "params": {"default_score": score}}


class _AlwaysFailsJudge(Judge):
    """A member that raises on evaluate() -- a real outage, not the construction-time
    RegistryError an unknown member *type* would raise instead (JUDGES.create resolves
    member types eagerly, before evaluate() is ever reachable)."""

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        raise RuntimeError("member outage")


class TestPanelJudge:
    """``panel`` judge test matrix."""

    MATRIX_KIND = "judge"
    MATRIX_COMPONENTS = ("panel",)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_median_strategy(self) -> None:
        j = JUDGES.create("panel", {"members": [_mock_member(0.2), _mock_member(0.9), _mock_member(0.5)]})
        v = j.evaluate("prompt")
        assert v.score == 0.5

    def test_m1_correctness_mean_strategy(self) -> None:
        j = JUDGES.create("panel", {"members": [_mock_member(0.0), _mock_member(1.0)], "strategy": "mean"})
        v = j.evaluate("prompt")
        assert v.score == 0.5

    def test_m1_correctness_majority_strategy_is_a_pass_fraction(self) -> None:
        j = JUDGES.create(
            "panel",
            {"members": [_mock_member(0.9), _mock_member(0.1)], "strategy": "majority", "member_pass_threshold": 0.5},
        )
        v = j.evaluate("prompt")
        assert v.score == 0.5  # 1 of 2 members clears the pass threshold

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_below_quorum_abstains_rather_than_crashing(self) -> None:
        JUDGES.register_class("_test_panel_matrix_always_fails", _AlwaysFailsJudge)
        try:
            j = JUDGES.create("panel", {"members": [_mock_member(0.7), {"type": "_test_panel_matrix_always_fails"}]})
            v = j.evaluate("prompt")  # 1 survivor < default quorum of 2 -> abstain, not a crash
            assert v.raw["abstained"] is True
            assert len(v.raw["failed_members"]) == 1
        finally:
            JUDGES._reg.pop("_test_panel_matrix_always_fails", None)

    def test_m2_edge_empty_prompt(self) -> None:
        j = JUDGES.create("panel", {"members": [_mock_member(0.4), _mock_member(0.6)]})
        v = j.evaluate("")
        assert v.score == 0.5

    def test_m2_edge_quorum_equal_to_full_member_count_is_unanimity(self) -> None:
        j = JUDGES.create("panel", {"members": [_mock_member(0.3), _mock_member(0.3), _mock_member(0.9)], "quorum": 3})
        v = j.evaluate("prompt")
        assert v.raw["abstained"] is False  # all 3 survive -> meets a full-unanimity quorum

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        j = JUDGES.create("panel", {"members": [_mock_member(0.4), _mock_member(0.6)]})
        v = j.evaluate("test")
        assert isinstance(v, JudgeVerdict)
        assert isinstance(v.score, float)
        assert isinstance(v.reasoning, str)
        assert isinstance(v.raw, dict)
        assert isinstance(v.raw["members"], list)
        assert isinstance(v.raw["abstained"], bool)

    # -------------------------------------------------------------- M5: determinism (voluntary)

    def test_m5_determinism(self) -> None:
        j = JUDGES.create(
            "panel", {"members": [_mock_member(0.2), _mock_member(0.9), _mock_member(0.5)], "strategy": "median"}
        )
        results = [j.evaluate("x marks the spot") for _ in range(10)]
        assert all(r.score == results[0].score for r in results)
        assert all(r.raw["spread"] == results[0].raw["spread"] for r in results)

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_single_member_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least two members"):
            JUDGES.create("panel", {"members": [_mock_member(0.5)]})

    def test_m6_error_unknown_strategy_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy"):
            JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "strategy": "geomean"})

    def test_m6_error_quorum_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="quorum must be between"):
            JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "quorum": 0})
