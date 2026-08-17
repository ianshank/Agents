"""Unit tests for implreview.locate: no real git repo or subprocess required."""

from __future__ import annotations

from pathlib import Path

import pytest
from implreview.locate import (
    ChangeNotFoundError,
    current_branch_name,
    current_tree_sha,
    infer_change_id,
    list_change_ids,
    locate_change,
    parse_tasks_status,
    recent_commit_subjects,
)


def _make_change(
    repo_root: Path, change_id: str, *, tasks_text: str | None = "- [x] done\n", with_review: bool = False
) -> Path:
    change_dir = repo_root / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text(f"# Change: {change_id}\n", encoding="utf-8")
    if tasks_text is not None:
        (change_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
    if with_review:
        (change_dir / "review.md").write_text(f"# Review: {change_id}\n", encoding="utf-8")
    return change_dir


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "openspec" / "changes").mkdir(parents=True)
    return tmp_path


# --- parse_tasks_status ------------------------------------------------------------------


def test_parse_tasks_status_all_checked_is_complete() -> None:
    status = parse_tasks_status("- [x] one\n- [X] two\n")
    assert status.total == 2
    assert status.checked == 2
    assert status.complete is True
    assert status.unchecked_items == ()


def test_parse_tasks_status_some_unchecked_is_incomplete() -> None:
    status = parse_tasks_status("- [x] done\n- [ ] not done\n- [ ] also not done\n")
    assert status.total == 3
    assert status.checked == 1
    assert status.complete is False
    assert status.unchecked_items == ("not done", "also not done")
    assert 0 < status.fraction_complete < 1


def test_parse_tasks_status_no_checkboxes_is_not_complete() -> None:
    status = parse_tasks_status("# Tasks\n\nJust prose, no checkboxes.\n")
    assert status.total == 0
    assert status.complete is False
    assert status.fraction_complete == 0.0


def test_parse_tasks_status_protected_marker_does_not_confuse_the_checkbox_regex() -> None:
    # This repo's own tasks.md convention: a `[P]` protected-path marker follows the real
    # checkbox on the same line. It must never be mistaken for a second checkbox.
    status = parse_tasks_status("- [ ] `[P]` PanelJudge in src/eval_harness/judges/.\n")
    assert status.total == 1
    assert status.checked == 0
    assert status.unchecked_items == ("`[P]` PanelJudge in src/eval_harness/judges/.",)


def test_parse_tasks_status_respects_unchecked_limit() -> None:
    text = "".join(f"- [ ] item {i}\n" for i in range(10))
    status = parse_tasks_status(text, unchecked_limit=3)
    assert status.total == 10
    assert len(status.unchecked_items) == 3


# --- list_change_ids ----------------------------------------------------------------------


def test_list_change_ids_excludes_archive_and_sorts(repo_root: Path) -> None:
    _make_change(repo_root, "zeta")
    _make_change(repo_root, "alpha")
    (repo_root / "openspec" / "changes" / "archive").mkdir()
    assert list_change_ids(repo_root / "openspec" / "changes") == ("alpha", "zeta")


def test_list_change_ids_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert list_change_ids(tmp_path / "nope") == ()


# --- infer_change_id ------------------------------------------------------------------------


def test_infer_change_id_matches_branch_name_first(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    _make_change(repo_root, "harden-quality-gate-integrity")
    changes_root = repo_root / "openspec" / "changes"
    change_id, source = infer_change_id(
        changes_root,
        branch_name="worktree-add-panel-judge",
        recent_subjects=("unrelated commit",),
    )
    assert (change_id, source) == ("add-panel-judge", "branch")


def test_infer_change_id_falls_back_to_commit_subjects(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    changes_root = repo_root / "openspec" / "changes"
    change_id, source = infer_change_id(
        changes_root,
        branch_name="worktree-agent-a4ae4f1a71d66d576",
        recent_subjects=("chore: unrelated", "docs(add-panel-judge): independent review"),
    )
    assert (change_id, source) == ("add-panel-judge", "commit")


def test_infer_change_id_no_match_returns_none_none(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    changes_root = repo_root / "openspec" / "changes"
    assert infer_change_id(changes_root, branch_name="unrelated", recent_subjects=("also unrelated",)) == (None, None)


def test_infer_change_id_no_candidates_at_all(tmp_path: Path) -> None:
    assert infer_change_id(tmp_path / "nope", branch_name="anything", recent_subjects=()) == (None, None)


def test_infer_change_id_with_no_branch_name_falls_straight_to_commits(repo_root: Path) -> None:
    # branch_name=None (detached HEAD, or git unavailable) must skip straight to the commit
    # scan rather than erroring or short-circuiting.
    _make_change(repo_root, "add-panel-judge")
    changes_root = repo_root / "openspec" / "changes"
    change_id, source = infer_change_id(
        changes_root, branch_name=None, recent_subjects=("docs(add-panel-judge): review",)
    )
    assert (change_id, source) == ("add-panel-judge", "commit")


def test_infer_change_id_does_not_match_a_direct_alphanumeric_extension(repo_root: Path) -> None:
    # "lint" must not match inside "linter-tool" -- a direct letter extension, not a
    # hyphen-delimited token. Hyphens are always acceptable boundaries (the repo's own
    # worktree-<id> convention and "docs(<id>): ..." commit style both rely on that), so this
    # checks the boundary that must still hold: no bare alphanumeric extension either side.
    _make_change(repo_root, "lint")
    changes_root = repo_root / "openspec" / "changes"
    change_id, source = infer_change_id(changes_root, branch_name="linter-tool-rewrite", recent_subjects=())
    assert (change_id, source) == (None, None)


def test_infer_change_id_prefers_the_longer_more_specific_candidate(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    _make_change(repo_root, "add-panel-judge-extended")
    changes_root = repo_root / "openspec" / "changes"
    change_id, source = infer_change_id(
        changes_root, branch_name="worktree-add-panel-judge-extended", recent_subjects=()
    )
    assert (change_id, source) == ("add-panel-judge-extended", "branch")


# --- locate_change --------------------------------------------------------------------------


def test_locate_change_explicit_id_found(repo_root: Path) -> None:
    change_dir = _make_change(repo_root, "add-panel-judge", with_review=True)
    result = locate_change(repo_root, "add-panel-judge")
    assert result.change_id == "add-panel-judge"
    assert result.change_dir == change_dir
    assert result.inferred is False
    assert result.inferred_from is None
    assert result.tasks_status is not None
    assert result.tasks_status.complete is True
    assert result.review_exists is True
    assert result.review_path == change_dir / "review.md"


def test_locate_change_explicit_id_not_found_lists_known_changes(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    with pytest.raises(ChangeNotFoundError, match="add-panel-judge"):
        locate_change(repo_root, "totally-bogus-change-id")


def test_locate_change_missing_tasks_md_reports_none_status(repo_root: Path) -> None:
    _make_change(repo_root, "no-tasks-yet", tasks_text=None)
    result = locate_change(repo_root, "no-tasks-yet")
    assert result.tasks_status is None


def test_locate_change_infers_from_branch(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    result = locate_change(repo_root, None, branch_name="worktree-add-panel-judge", recent_subjects=())
    assert result.change_id == "add-panel-judge"
    assert result.inferred is True
    assert result.inferred_from == "branch"


def test_locate_change_infers_from_commits_when_branch_does_not_match(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    result = locate_change(
        repo_root,
        None,
        branch_name="worktree-agent-hash",
        recent_subjects=("docs(add-panel-judge): review",),
    )
    assert result.inferred_from == "commit"


def test_locate_change_inference_failure_raises_with_context(repo_root: Path) -> None:
    _make_change(repo_root, "add-panel-judge")
    with pytest.raises(ChangeNotFoundError, match="no change id was given"):
        locate_change(repo_root, None, branch_name="nope", recent_subjects=("also nope",))


def test_locate_change_review_not_existing(repo_root: Path) -> None:
    _make_change(repo_root, "fresh-change", with_review=False)
    result = locate_change(repo_root, "fresh-change")
    assert result.review_exists is False


# --- git-backed helpers (injectable `run`, no real subprocess) ----------------------------


def test_current_branch_name_uses_injected_run(tmp_path: Path) -> None:
    assert current_branch_name(tmp_path, run=lambda root, args: "my-branch") == "my-branch"


def test_current_branch_name_empty_output_is_none(tmp_path: Path) -> None:
    assert current_branch_name(tmp_path, run=lambda root, args: "") is None


def test_current_branch_name_run_failure_is_none(tmp_path: Path) -> None:
    assert current_branch_name(tmp_path, run=lambda root, args: None) is None


def test_recent_commit_subjects_splits_lines(tmp_path: Path) -> None:
    subjects = recent_commit_subjects(tmp_path, run=lambda root, args: "first\nsecond\nthird")
    assert subjects == ("first", "second", "third")


def test_recent_commit_subjects_unavailable_is_empty(tmp_path: Path) -> None:
    assert recent_commit_subjects(tmp_path, run=lambda root, args: None) == ()


def test_current_tree_sha_uses_injected_run(tmp_path: Path) -> None:
    assert current_tree_sha(tmp_path, run=lambda root, args: "deadbeef") == "deadbeef"


def test_current_tree_sha_unavailable_is_none(tmp_path: Path) -> None:
    assert current_tree_sha(tmp_path, run=lambda root, args: None) is None


def test_run_git_against_a_real_non_repo_directory_returns_none(tmp_path: Path) -> None:
    # Exercises the real subprocess path (the default `run=_run_git`) against a directory that
    # is genuinely not a git repository, so this does not depend on any actual git state.
    assert current_branch_name(tmp_path) is None
    assert current_tree_sha(tmp_path) is None
    assert recent_commit_subjects(tmp_path) == ()


def test_run_git_against_the_real_repo_succeeds_for_real(tmp_path: Path) -> None:
    # The real default `run=_run_git` path, against a genuine git repository (this skill's own
    # tree), not an injected fake -- proves the success branch (real subprocess, real stdout
    # parsing) actually works, not just the "not a repo" failure branch above.
    real_repo_root = Path(__file__).resolve().parents[3]
    sha = current_tree_sha(real_repo_root)
    assert sha is not None
    assert len(sha) == 40  # a real, full git SHA
    assert all(c in "0123456789abcdef" for c in sha)


def test_run_git_catches_a_subprocess_launch_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as _subprocess

    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("git binary not found")

    monkeypatch.setattr(_subprocess, "run", _raise)
    # Goes through the real `_run_git` (default `run=`), not an injected fake, so this
    # actually exercises the `except (OSError, subprocess.SubprocessError)` branch.
    assert current_branch_name(tmp_path) is None
