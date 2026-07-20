"""Unit tests for the PR-scoped subtree-isolation checker (real git in a tmp repo)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from backend_validation.isolation import IsolationError, check_isolation
from backend_validation.procrun import CompletedCommand, SubprocessRunner

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

RUNNER = SubprocessRunner()


def _git(repo: Path, *argv: str) -> None:
    result = RUNNER.run(["git", *argv], cwd=repo)
    assert result.ok, f"git {argv} failed: {result.stderr}"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "experiments" / "backend-validation").mkdir(parents=True)
    (repo / "experiments" / "backend-validation" / "README.md").write_text("x\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("log\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


ALLOWLIST = ("experiments/backend-validation/", "CHANGELOG.md")


def test_in_tree_changes_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "experiments" / "backend-validation" / "new.py").write_text("pass\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("log\nmore\n", encoding="utf-8")
    result = check_isolation(repo_root=repo, base_ref="HEAD", allowlist=ALLOWLIST, runner=RUNNER)
    assert result.ok and result.checked_paths == 2


def test_out_of_tree_untracked_file_is_a_violation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "src_sneaky.py").write_text("pass\n", encoding="utf-8")
    result = check_isolation(repo_root=repo, base_ref="HEAD", allowlist=ALLOWLIST, runner=RUNNER)
    assert not result.ok
    assert result.violations == ("src_sneaky.py",)


def test_committed_out_of_tree_change_is_a_violation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = RUNNER.run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    (repo / "outside.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "escape")
    result = check_isolation(repo_root=repo, base_ref=base, allowlist=ALLOWLIST, runner=RUNNER)
    assert not result.ok and "outside.txt" in result.violations


def test_rename_checks_the_destination(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = repo / "experiments" / "backend-validation" / "README.md"
    _git(repo, "mv", str(src.relative_to(repo)), "ESCAPED.md")
    result = check_isolation(repo_root=repo, base_ref="HEAD", allowlist=ALLOWLIST, runner=RUNNER)
    assert not result.ok and "ESCAPED.md" in result.violations


def test_git_failure_raises_isolation_error(tmp_path: Path) -> None:
    class FailingRunner:
        def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=128, stderr="fatal: not a git repository")

    with pytest.raises(IsolationError, match="git diff"):
        check_isolation(repo_root=tmp_path, base_ref="HEAD", allowlist=(), runner=FailingRunner())


def test_git_status_failure_raises(tmp_path: Path) -> None:
    class DiffOkStatusFail:
        def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
            if "diff" in argv:
                return CompletedCommand(tuple(argv), returncode=0, stdout="")
            return CompletedCommand(tuple(argv), returncode=1, stderr="boom")

    with pytest.raises(IsolationError, match="git status"):
        check_isolation(repo_root=tmp_path, base_ref="HEAD", allowlist=(), runner=DiffOkStatusFail())
