"""Unit tests for implreview.prompts: prompt composition, no live dispatch involved."""

from __future__ import annotations

from pathlib import Path

from implreview.locate import ChangeLocation
from implreview.prompts import (
    PRECEDENT_REVIEW,
    SECOND_PRECEDENT_REVIEW,
    build_degraded_prompt,
    build_dispatch_plan,
    build_peer_reviewer_prompt,
    build_spec_guardian_prompt,
)


def _change(tmp_path: Path, change_id: str = "add-openspec-implementation-review") -> ChangeLocation:
    change_dir = tmp_path / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True)
    return ChangeLocation(
        change_id=change_id,
        change_dir=change_dir,
        inferred=False,
        inferred_from=None,
        tasks_status=None,
        review_path=change_dir / "review.md",
        review_exists=False,
    )


def test_spec_guardian_prompt_names_the_target(tmp_path: Path) -> None:
    change = _change(tmp_path)
    dispatch = build_spec_guardian_prompt(change, "deadbeef")
    assert dispatch.subagent_type == "spec-guardian"
    assert change.change_id in dispatch.prompt
    assert str(change.change_dir) in dispatch.prompt
    assert "deadbeef" in dispatch.prompt
    assert "Verdict: conforms" in dispatch.prompt


def test_peer_reviewer_prompt_specifies_the_output_shape(tmp_path: Path) -> None:
    change = _change(tmp_path)
    dispatch = build_peer_reviewer_prompt(change, "deadbeef")
    assert dispatch.subagent_type == "peer-reviewer"
    assert str(change.review_path) in dispatch.prompt
    assert PRECEDENT_REVIEW in dispatch.prompt
    assert SECOND_PRECEDENT_REVIEW in dispatch.prompt
    assert "## Verdict" in dispatch.prompt
    assert "## Pass 1" in dispatch.prompt
    assert "## Pass 2" in dispatch.prompt
    assert "## Overall verdict" in dispatch.prompt


def test_peer_reviewer_and_degraded_prompts_never_instruct_the_dispatched_agent_to_write_the_file(
    tmp_path: Path,
) -> None:
    # Regression test for a real, reproduced bug (Phase 5 independent review, pass 2a): the
    # output-shape template used to say "Write the result to {review_path}", which conflicts
    # with SKILL.md's documented flow -- the ORCHESTRATOR captures the dispatched agent's text
    # output and writes the file via `compose`, exactly once. A dispatched general-purpose
    # subagent plausibly has its own Write tool and nothing told it not to use it, so a real
    # dispatch could double-write duplicated content. Both prompt shapes that reach the output
    # contract (peer-reviewer and degraded) must instruct the dispatched agent to return text
    # only, and must say so explicitly rather than leaving it implicit.
    change = _change(tmp_path)
    for dispatch in (
        build_peer_reviewer_prompt(change, "deadbeef"),
        build_degraded_prompt(change, "deadbeef"),
    ):
        assert "write the result to" not in dispatch.prompt.lower(), dispatch.subagent_type
        assert "do not write, create, or edit" in dispatch.prompt.lower(), dispatch.subagent_type
        assert "orchestrating agent captures" in dispatch.prompt.lower(), dispatch.subagent_type
        assert str(change.review_path) in dispatch.prompt, dispatch.subagent_type


def test_peer_reviewer_prompt_includes_spec_guardian_handoff_when_given(tmp_path: Path) -> None:
    change = _change(tmp_path)
    dispatch = build_peer_reviewer_prompt(change, "deadbeef", spec_guardian_findings="Verdict: conforms\n1. ...")
    assert "spec-guardian's conformance findings" in dispatch.prompt
    assert "Verdict: conforms" in dispatch.prompt


def test_peer_reviewer_prompt_omits_handoff_block_when_not_given(tmp_path: Path) -> None:
    change = _change(tmp_path)
    dispatch = build_peer_reviewer_prompt(change, "deadbeef")
    assert "spec-guardian's conformance findings" not in dispatch.prompt


def test_degraded_prompt_is_self_contained(tmp_path: Path) -> None:
    change = _change(tmp_path)
    dispatch = build_degraded_prompt(change, "deadbeef")
    assert dispatch.subagent_type == "general-purpose"
    # The whole two-pass method must be inlined -- no charter to fall back on.
    for marker in (
        "PASS 1",
        "PASS 2",
        "CONFIRMED",
        "CORRECTED",
        "REFUTED",
        "RECORDED AS REFUTED",
        "ADR 0028",
        "claude-foundation",
    ):
        assert marker in dispatch.prompt, f"missing {marker!r} in degraded prompt"
    assert PRECEDENT_REVIEW in dispatch.prompt
    assert SECOND_PRECEDENT_REVIEW in dispatch.prompt
    assert change.change_id in dispatch.prompt
    assert "deadbeef" in dispatch.prompt
    assert str(change.review_path) in dispatch.prompt


def test_degraded_prompt_specifies_the_same_output_shape_as_peer_reviewer(tmp_path: Path) -> None:
    change = _change(tmp_path)
    degraded = build_degraded_prompt(change, "deadbeef")
    peer = build_peer_reviewer_prompt(change, "deadbeef")
    for heading in ("## Verdict", "## Pass 1", "## Pass 2", "## Residual risk", "## Overall verdict"):
        assert heading in degraded.prompt
        assert heading in peer.prompt


def test_dispatch_plan_plugin_path_is_spec_guardian_then_peer_reviewer(tmp_path: Path) -> None:
    change = _change(tmp_path)
    plan = build_dispatch_plan(change, "deadbeef", "plugin")
    assert plan.path == "plugin"
    assert [p.subagent_type for p in plan.prompts] == ["spec-guardian", "peer-reviewer"]


def test_dispatch_plan_degraded_path_is_one_general_purpose_dispatch(tmp_path: Path) -> None:
    change = _change(tmp_path)
    plan = build_dispatch_plan(change, "deadbeef", "degraded")
    assert plan.path == "degraded"
    assert [p.subagent_type for p in plan.prompts] == ["general-purpose"]
