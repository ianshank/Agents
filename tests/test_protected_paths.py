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
