"""Matrix row for the agent-in-the-loop testgen pipeline target (floor M1, M2, M3, M6)."""

from __future__ import annotations

from eval_harness.core.types import TESTGEN_EVIDENCE_KEY, EvalItem, TargetOutput
from eval_harness.plugins import TARGETS
from tests._testgen_agent_fixtures import KILLING_SUITE
from tests.test_testgen_target import item as _inputs

_HOLDOUT = {"split": "holdout"}


def _item(suite: str = "SECRET") -> EvalItem:
    return EvalItem(id="m", inputs=_inputs(suite), metadata=dict(_HOLDOUT))


class TestTestgenAgentTarget:
    """Target-kind row for the sequential generator → execute pipeline."""

    MATRIX_KIND = "target"
    MATRIX_COMPONENTS = ("testgen_agent",)

    def test_m1_correctness_generated_killing_suite_covers_and_kills(self) -> None:
        target = TARGETS.create("testgen_agent", {"generate": lambda _view: KILLING_SUITE})
        out = target.run(_item())
        assert isinstance(out, TargetOutput)
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["mutants"]["killed"] == 1

    def test_m2_edge_missing_generator_fail_closes_with_empty_evidence(self) -> None:
        out = TARGETS.create("testgen_agent", {}).run(_item())
        assert out.error is not None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_m3_type_non_string_generation_is_an_error_not_a_crash(self) -> None:
        out = TARGETS.create("testgen_agent", {"generate": lambda _view: {"suite": "nope"}}).run(_item())
        assert out.error is not None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_m6_error_disallowed_split_is_structured_not_raised(self) -> None:
        it = EvalItem(id="m", inputs=_inputs("SECRET"), metadata={"split": "train"})
        out = TARGETS.create("testgen_agent", {"generate": lambda _view: KILLING_SUITE}).run(it)
        assert out.error is not None
        assert "train" in (out.error or "")
