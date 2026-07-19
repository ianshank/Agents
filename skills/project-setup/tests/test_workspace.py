"""Unit tests for monorepo workspace detection (``makegen.workspace``)."""

from __future__ import annotations

from pathlib import Path

from makegen import detect_workspace


def _member(root: Path, name: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "pyproject.toml").write_text(f'[project]\nname="{name}"\n', encoding="utf-8")


def test_members_are_sorted_immediate_children(tmp_path: Path) -> None:
    _member(tmp_path, "zeta-pkg")
    _member(tmp_path, "alpha-pkg")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="root"\n', encoding="utf-8")
    ws = detect_workspace(tmp_path)
    assert ws.members == ("alpha-pkg", "zeta-pkg")  # sorted, root's own pyproject excluded
    assert ws.is_workspace is True


def test_nested_pyprojects_are_not_members(tmp_path: Path) -> None:
    # The immediate-child rule excludes fixtures/vendored trees with no exclude list.
    deep = tmp_path / "skills" / "some-skill" / "evals" / "fixtures" / "proj"
    deep.mkdir(parents=True)
    (deep / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert detect_workspace(tmp_path).members == ()


def test_dirs_without_pyproject_are_not_members(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    assert detect_workspace(tmp_path).members == ()


def test_hidden_dirs_are_never_members(tmp_path: Path) -> None:
    hidden = tmp_path / ".venv-thing"
    hidden.mkdir()
    (hidden / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert detect_workspace(tmp_path).members == ()


def test_unsafe_names_are_skipped_not_emitted(tmp_path: Path) -> None:
    _member(tmp_path, "good-pkg")
    bad = tmp_path / "bad pkg"
    bad.mkdir()
    (bad / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    ws = detect_workspace(tmp_path)
    assert ws.members == ("good-pkg",)
    assert ws.skipped == ("bad pkg",)  # visible, never silently emitted broken


def test_reserved_name_all_is_skipped(tmp_path: Path) -> None:
    # A member named `all` would make check-all/install-all/clean-all duplicate targets
    # (GNU Make: last recipe wins + warning), silently dropping the member's delegation.
    _member(tmp_path, "all")
    _member(tmp_path, "fine-pkg")
    ws = detect_workspace(tmp_path)
    assert ws.members == ("fine-pkg",)
    assert ws.skipped == ("all",)


def test_missing_root_is_empty_workspace(tmp_path: Path) -> None:
    ws = detect_workspace(tmp_path / "nope")
    assert ws.members == () and ws.is_workspace is False


def test_deterministic(tmp_path: Path) -> None:
    _member(tmp_path, "a")
    _member(tmp_path, "b")
    assert detect_workspace(tmp_path) == detect_workspace(tmp_path)
