#!/usr/bin/env python3
"""Tests for the eval-integrity protected-path matcher and CI guard."""

from __future__ import annotations

import check_protected_changes as guard
import eval_protected_paths as epp
import pytest

# ---------------------------------------------------------------------------
# Matcher: every protected glob is blocked
# ---------------------------------------------------------------------------

PROTECTED_EXAMPLES = [
    "features.yaml",
    "features.schema.json",
    "scripts/validations/F_006.py",
    "config/eval.example.yaml",
    "config/nested/deep.yaml",
    "src/eval_harness/gating/__init__.py",
    "src/eval_harness/scorers/__init__.py",
    "src/eval_harness/judges/__init__.py",
    "tests/test_engine.py",
    ".github/workflows/eval-harness-ci.yml",
    ".github/CODEOWNERS",
]

ALLOWED_EXAMPLES = [
    "src/eval_harness/engine.py",
    "src/eval_harness/cli.py",
    "src/eval_harness/datasets/__init__.py",
    "src/eval_harness/targets/__init__.py",
    "src/eval_harness/sinks/__init__.py",
    "src/eval_harness/core/types.py",
    "src/eval_harness/langfuse_client/__init__.py",
    "README.md",
    "scripts/regression_gate.py",
]


@pytest.mark.parametrize("path", PROTECTED_EXAMPLES)
def test_protected_paths_are_blocked(path: str) -> None:
    assert epp.is_protected(path) is True


@pytest.mark.parametrize("path", ALLOWED_EXAMPLES)
def test_implementation_paths_are_allowed(path: str) -> None:
    assert epp.is_protected(path) is False


def test_normalisation_handles_prefixes() -> None:
    assert epp.is_protected("./features.yaml") is True
    assert epp.is_protected("tests\\test_x.py") is True


def test_matched_protected_dedupes_and_sorts() -> None:
    mixed = ["src/eval_harness/engine.py", "config/a.yaml", "tests/x.py", "config/a.yaml"]
    assert epp.matched_protected(mixed) == ["config/a.yaml", "tests/x.py"]


# ---------------------------------------------------------------------------
# Glob translation + normalisation internals
# ---------------------------------------------------------------------------


def test_glob_to_regex_question_and_star_do_not_cross_separator() -> None:
    rx = epp._glob_to_regex("a?b*c")
    assert rx.match("axbZZc")
    assert rx.match("axbc")
    assert not rx.match("a/bc")


def test_glob_to_regex_double_star_middle_crosses_separators() -> None:
    rx = epp._glob_to_regex("a/**/b")
    assert rx.match("a/b")
    assert rx.match("a/x/y/b")
    assert not rx.match("a/x/y")


def test_normalise_strips_repeated_dot_slash_and_leading_slash() -> None:
    assert epp._normalise("././a/b") == "a/b"
    assert epp._normalise("/a/b") == "a/b"


# ---------------------------------------------------------------------------
# Label parsing
# ---------------------------------------------------------------------------


def test_parse_labels_json_objects() -> None:
    raw = '[{"name": "eval-change-approved"}, {"name": "bug"}]'
    assert guard.parse_labels(raw) == {"eval-change-approved", "bug"}


def test_parse_labels_comma_and_space() -> None:
    assert guard.parse_labels("a, b c") == {"a", "b", "c"}


def test_parse_labels_empty() -> None:
    assert guard.parse_labels(None) == set()
    assert guard.parse_labels("") == set()


def test_parse_labels_json_strings() -> None:
    assert guard.parse_labels('["a", "b"]') == {"a", "b"}


def test_parse_labels_invalid_json_returns_empty() -> None:
    assert guard.parse_labels("[not valid json") == set()


# ---------------------------------------------------------------------------
# git-backed diff resolution + config-error path
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_changed_files_from_git(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "base"], repo)
    (repo / "added.py").write_text("x = 1\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "second"], repo)

    monkeypatch.chdir(repo)
    changed = guard.changed_files_from_git("HEAD~1")
    assert "added.py" in changed


def test_guard_config_error_on_unknown_ref(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "base"], repo)

    monkeypatch.chdir(repo)
    # No --files, and an unresolvable base ref => configuration error (exit 2).
    assert guard.main(["--base-ref", "no-such-ref-xyz"]) == 2


# ---------------------------------------------------------------------------
# Guard CLI behaviour (via main(argv))
# ---------------------------------------------------------------------------


def test_guard_blocks_protected_without_approval() -> None:
    assert guard.main(["--files", "config/eval.example.yaml"]) == 1


def test_guard_allows_protected_with_flag() -> None:
    assert guard.main(["--files", "config/eval.example.yaml", "--approved"]) == 0


def test_guard_allows_protected_with_label() -> None:
    rc = guard.main(["--files", "features.yaml", "--labels", "eval-change-approved"])
    assert rc == 0


def test_guard_allows_implementation_only_change() -> None:
    assert guard.main(["--files", "src/eval_harness/engine.py"]) == 0


def test_guard_label_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_LABELS", '[{"name": "eval-change-approved"}]')
    assert guard.main(["--files", "tests/test_x.py"]) == 0


def test_guard_custom_approval_label() -> None:
    rc = guard.main(["--files", "config/x.yaml", "--labels", "ok", "--approval-label", "ok"])
    assert rc == 0
