"""Tests for :class:`~eval_harness.judges.panel.PanelJudge`.

Member judges are driven either by ``mock`` (via config, scored by ``default_score``)
or by small local stub :class:`Judge` implementations registered through the same
registry ``PanelJudge`` itself uses (mirrors ``test_composite_scorer.py``'s
``_NoneScorer`` pattern) -- each stub is registered and torn down per-test via a
fixture so no test-only name leaks into the shared registry baseline.
"""

from __future__ import annotations

import pytest

from eval_harness.core.interfaces import Judge
from eval_harness.core.registry import RegistryError
from eval_harness.core.types import JudgeVerdict
from eval_harness.judges import MockJudge
from eval_harness.plugins import JUDGES


def _mock_member(score: float, name: str | None = None) -> dict:
    spec = {"type": "mock", "params": {"default_score": score}}
    if name is not None:
        spec["name"] = name
    return spec


class _RaisingJudge(Judge):
    def __init__(self, message: str = "member outage"):
        self.message = message

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        raise RuntimeError(self.message)


class _RecordingJudge(Judge):
    """Appends its label to a shared list on each call, to prove call order."""

    def __init__(self, score: float = 1.0, log: list | None = None, label: str = ""):
        self.score = score
        self.log = log if log is not None else []
        self.label = label

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        self.log.append(self.label)
        return JudgeVerdict(score=self.score, reasoning="")


class _AttachableJudge(Judge):
    def __init__(self, score: float = 1.0):
        self.score = score
        self.attached = None

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        return JudgeVerdict(score=self.score, reasoning="")

    def attach_client(self, client) -> None:
        self.attached = client


@pytest.fixture
def raising_judge_type():
    name = "panel_test_raising"
    JUDGES.register_class(name, _RaisingJudge)
    try:
        yield name
    finally:
        JUDGES._reg.pop(name, None)


@pytest.fixture
def recording_judge_type():
    name = "panel_test_recording"
    JUDGES.register_class(name, _RecordingJudge)
    try:
        yield name
    finally:
        JUDGES._reg.pop(name, None)


@pytest.fixture
def attachable_judge_type():
    name = "panel_test_attachable"
    JUDGES.register_class(name, _AttachableJudge)
    try:
        yield name
    finally:
        JUDGES._reg.pop(name, None)


# --------------------------------------------------------------------------- registration


def test_registered_with_no_alias():
    assert "panel" in JUDGES.names()
    assert JUDGES.resolve("panel") == "panel"


def test_construction_via_registry():
    judge = JUDGES.create("panel", {"members": [_mock_member(0.4), _mock_member(0.6)]})
    from eval_harness.judges.panel import PanelJudge

    assert isinstance(judge, PanelJudge)


# --------------------------------------------------------------------------- construction validation


def test_empty_members_raises():
    with pytest.raises(ValueError, match="at least one member"):
        JUDGES.create("panel", {"members": []})


def test_single_member_raises():
    with pytest.raises(ValueError, match="at least two members"):
        JUDGES.create("panel", {"members": [_mock_member(0.5)]})


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="unknown strategy"):
        JUDGES.create("panel", {"members": [_mock_member(0.1), _mock_member(0.9)], "strategy": "geomean"})


def test_non_dict_member_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        JUDGES.create("panel", {"members": [_mock_member(0.1), "not-a-dict"]})


def test_member_missing_type_raises():
    with pytest.raises(ValueError, match="must specify a 'type'"):
        JUDGES.create("panel", {"members": [_mock_member(0.1), {"params": {}}]})


def test_unknown_member_type_propagates_registry_error():
    with pytest.raises(RegistryError):
        JUDGES.create("panel", {"members": [_mock_member(0.1), {"type": "does_not_exist"}]})


@pytest.mark.parametrize(("n_members", "expected_default_quorum"), [(2, 2), (3, 2), (4, 3), (5, 3)])
def test_default_quorum_is_simple_majority(n_members, expected_default_quorum):
    members = [_mock_member(0.5) for _ in range(n_members)]
    judge = JUDGES.create("panel", {"members": members})
    assert judge.quorum == expected_default_quorum


def test_quorum_equal_to_member_count_is_valid_unanimity():
    members = [_mock_member(0.5), _mock_member(0.5), _mock_member(0.5)]
    judge = JUDGES.create("panel", {"members": members, "quorum": 3})
    assert judge.quorum == 3


@pytest.mark.parametrize("bad_quorum", [0, -1, 4])
def test_quorum_out_of_range_raises(bad_quorum):
    members = [_mock_member(0.5), _mock_member(0.5), _mock_member(0.5)]
    with pytest.raises(ValueError, match="quorum must be between"):
        JUDGES.create("panel", {"members": members, "quorum": bad_quorum})


# --------------------------------------------------------------------------- aggregation strategies


def test_median_strategy_odd_member_count():
    members = [_mock_member(0.2), _mock_member(0.9), _mock_member(0.5)]
    judge = JUDGES.create("panel", {"members": members, "strategy": "median"})
    verdict = judge.evaluate("prompt")
    assert verdict.score == pytest.approx(0.5)
    assert verdict.raw["abstained"] is False


def test_median_strategy_even_member_count_averages_middle_two():
    members = [_mock_member(0.2), _mock_member(0.8)]
    judge = JUDGES.create("panel", {"members": members, "strategy": "median"})
    verdict = judge.evaluate("prompt")
    assert verdict.score == pytest.approx(0.5)


def test_mean_strategy():
    members = [_mock_member(0.0), _mock_member(0.5), _mock_member(1.0)]
    judge = JUDGES.create("panel", {"members": members, "strategy": "mean"})
    verdict = judge.evaluate("prompt")
    assert verdict.score == pytest.approx(0.5)


def test_majority_strategy_is_a_pass_fraction_not_a_member_score():
    members = [_mock_member(0.9), _mock_member(0.9), _mock_member(0.1)]
    judge = JUDGES.create("panel", {"members": members, "strategy": "majority", "member_pass_threshold": 0.5})
    verdict = judge.evaluate("prompt")
    assert verdict.score == pytest.approx(2 / 3)


def test_majority_strategy_boundary_is_inclusive():
    members = [_mock_member(0.5), _mock_member(0.5)]
    judge = JUDGES.create("panel", {"members": members, "strategy": "majority", "member_pass_threshold": 0.5})
    verdict = judge.evaluate("prompt")
    assert verdict.score == pytest.approx(1.0)  # both members clear >= 0.5


def test_spread_and_stdev_are_reported_on_a_non_abstained_verdict():
    members = [_mock_member(0.0), _mock_member(1.0)]
    judge = JUDGES.create("panel", {"members": members})
    verdict = judge.evaluate("prompt")
    assert verdict.raw["spread"] == pytest.approx(1.0)
    assert verdict.raw["stdev"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- abstention


def test_abstains_below_quorum_when_a_member_fails(raising_judge_type):
    members = [_mock_member(0.7), {"type": raising_judge_type}]
    judge = JUDGES.create("panel", {"members": members, "on_skip": 0.25})
    verdict = judge.evaluate("prompt")
    assert verdict.raw["abstained"] is True
    assert verdict.score == pytest.approx(0.25)
    assert "below quorum" in verdict.reasoning
    assert verdict.raw["spread"] is None  # never computed -- quorum check runs first


def test_failed_member_is_excluded_not_fabricated_as_zero():
    # 3 members, 1 fails: 2 survivors clears the default quorum of 2, so the panel
    # still produces a real verdict computed only from the survivors.
    JUDGES.register_class("panel_test_raising2", _RaisingJudge)
    try:
        members = [_mock_member(0.8), _mock_member(0.6), {"type": "panel_test_raising2"}]
        judge = JUDGES.create("panel", {"members": members, "strategy": "mean"})
        verdict = judge.evaluate("prompt")
        assert verdict.raw["abstained"] is False
        assert verdict.score == pytest.approx(0.7)  # mean of 0.8 and 0.6 only
        assert len(verdict.raw["members"]) == 2
        assert len(verdict.raw["failed_members"]) == 1
        assert verdict.raw["failed_members"][0]["error"] == "member outage"
    finally:
        JUDGES._reg.pop("panel_test_raising2", None)


def test_abstains_when_disagreement_exceeds_threshold():
    members = [_mock_member(0.0), _mock_member(1.0)]
    judge = JUDGES.create("panel", {"members": members, "disagreement_threshold": 0.1})
    verdict = judge.evaluate("prompt")
    assert verdict.raw["abstained"] is True
    assert "disagreement" in verdict.reasoning
    assert verdict.raw["spread"] == pytest.approx(1.0)


def test_does_not_abstain_when_spread_is_within_threshold():
    members = [_mock_member(0.5), _mock_member(0.55)]
    judge = JUDGES.create("panel", {"members": members, "disagreement_threshold": 0.1})
    verdict = judge.evaluate("prompt")
    assert verdict.raw["abstained"] is False


def test_disagreement_threshold_none_by_default_never_abstains_on_spread():
    members = [_mock_member(0.0), _mock_member(1.0)]
    judge = JUDGES.create("panel", {"members": members})  # disagreement_threshold unset
    verdict = judge.evaluate("prompt")
    assert verdict.raw["abstained"] is False
    assert verdict.score == pytest.approx(0.5)


def test_on_skip_default_is_zero():
    members = [_mock_member(0.9), _mock_member(0.1)]
    judge = JUDGES.create("panel", {"members": members, "quorum": 2, "disagreement_threshold": 0.0})
    verdict = judge.evaluate("prompt")
    assert verdict.raw["abstained"] is True
    assert verdict.score == 0.0


# --------------------------------------------------------------------------- calls_per_evaluate


def test_calls_per_evaluate_sums_members_default_one():
    members = [_mock_member(0.1), _mock_member(0.2), _mock_member(0.3)]
    judge = JUDGES.create("panel", {"members": members})
    assert judge.calls_per_evaluate == 3


def test_calls_per_evaluate_is_recursive_for_a_nested_panel():
    # Outer panel has 2 top-level members: a nested 2-member panel (calls_per_evaluate=2)
    # and one plain mock (calls_per_evaluate=1, via the getattr default). The correct
    # total is 3 (sum of each member's own calls_per_evaluate) -- if the implementation
    # instead counted len(members) at the outer level, it would (wrongly) read 2.
    nested = {
        "type": "panel",
        "params": {"members": [_mock_member(0.1), _mock_member(0.2)]},
    }
    judge = JUDGES.create("panel", {"members": [nested, _mock_member(0.5)]})
    assert judge.calls_per_evaluate == 3


# --------------------------------------------------------------------------- labeling, ordering, attach_client


def test_member_label_defaults_to_type_and_index():
    members = [_mock_member(0.1), _mock_member(0.2)]
    judge = JUDGES.create("panel", {"members": members})
    verdict = judge.evaluate("prompt")
    names = [m["name"] for m in verdict.raw["members"]]
    assert names == ["mock#0", "mock#1"]


def test_member_label_uses_explicit_name_when_given():
    members = [_mock_member(0.1, name="senior_judge"), _mock_member(0.2)]
    judge = JUDGES.create("panel", {"members": members})
    verdict = judge.evaluate("prompt")
    names = [m["name"] for m in verdict.raw["members"]]
    assert names == ["senior_judge", "mock#1"]


def test_members_are_evaluated_sequentially_in_declaration_order(recording_judge_type):
    log: list[str] = []
    members = [
        {"type": recording_judge_type, "params": {"score": 0.3, "log": log, "label": "first"}},
        {"type": recording_judge_type, "params": {"score": 0.7, "log": log, "label": "second"}},
    ]
    judge = JUDGES.create("panel", {"members": members})
    judge.evaluate("prompt")
    assert log == ["first", "second"]


def test_attach_client_fans_out_only_to_members_that_support_it(attachable_judge_type):
    members = [
        {"type": attachable_judge_type, "params": {"score": 0.5}},
        _mock_member(0.5),  # MockJudge has no attach_client -- must be skipped, not raise
    ]
    judge = JUDGES.create("panel", {"members": members})
    sentinel = object()
    judge.attach_client(sentinel)
    attachable_member = judge._members[0][1]
    assert attachable_member.attached is sentinel


def test_members_are_built_once_at_construction_not_per_call():
    # Registry-built-children pattern (mirrors CompositeScorer): construct via a real
    # MockJudge instance check -- the same object identity is called on every evaluate().
    judge = JUDGES.create("panel", {"members": [_mock_member(0.4), _mock_member(0.6)]})
    first_member = judge._members[0][1]
    assert isinstance(first_member, MockJudge)
    judge.evaluate("a")
    judge.evaluate("b")
    assert judge._members[0][1] is first_member
