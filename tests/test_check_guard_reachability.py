"""Tests for the protected-path guard reachability check (F-052).

The point of this guard is that it *fires*. Several tests below are therefore mutation
tests: they delete a filter and assert the check fails. A guard that silently stops
detecting drift is worse than no guard, because the green tick is taken as evidence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from check_guard_reachability import (
    Coverage,
    GuardNotInvokedError,
    analyse,
    extract_path_filters,
    filter_matches,
    guard_is_invoked,
    main,
    render_text,
    sample_path_for,
    sample_paths_for,
)
from eval_protected_paths import PROTECTED_PATTERNS

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_WORKFLOW = Path(".github/workflows/quality-gates.yml")


# --- the live repository ------------------------------------------------------------


def test_every_protected_pattern_is_reachable_in_this_repo():
    """The regression this guard exists for: 9 of 15 were unreachable before F-052."""
    coverages, _ = analyse(REPO_ROOT)
    unreachable = [c.pattern for c in coverages if not c.reachable]
    assert not unreachable, f"protected but unreachable by the guard: {unreachable}"


def test_every_protected_pattern_is_accounted_for():
    coverages, _ = analyse(REPO_ROOT)
    assert {c.pattern for c in coverages} == set(PROTECTED_PATTERNS)


def test_architecture_yaml_is_reachable():
    """Called out separately: it is the airgap's enforcement surface."""
    coverages, _ = analyse(REPO_ROOT)
    entry = next(c for c in coverages if c.pattern == "architecture.yaml")
    assert entry.reachable


@pytest.mark.parametrize(
    "pattern",
    [
        "agent-core/tests/**",
        "behavioral-regression/tests/**",
        "flow-corpus/tests/**",
        "flow-protocol/tests/**",
        "claude-foundation/tests/**",
    ],
)
def test_every_sibling_test_root_is_reachable(pattern):
    coverages, _ = analyse(REPO_ROOT)
    assert next(c for c in coverages if c.pattern == pattern).reachable


def test_codeowners_is_covered_by_the_broadened_github_filter():
    """`.github/workflows/**` + `.github/actions/**` left CODEOWNERS outside the guard."""
    _, filters = analyse(REPO_ROOT)
    assert any(filter_matches(".github/CODEOWNERS", f) for f in filters)


# --- mutation tests: the guard must FAIL when the lists drift ------------------------


def _workflow_with_filter_removed(tmp_path: Path, removed: str) -> Path:
    """A copy of the real workflow with one path filter deleted."""
    text = (REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")
    mutated = "\n".join(line for line in text.splitlines() if line.strip() != f'- "{removed}"')
    assert mutated != text, f"filter {removed!r} was not present to remove"
    root = tmp_path / "repo"
    (root / GUARD_WORKFLOW.parent).mkdir(parents=True)
    (root / GUARD_WORKFLOW).write_text(mutated + "\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("removed", ["architecture.yaml", "config/**", "agent-core/tests/**", ".github/**"])
def test_removing_a_filter_makes_the_check_fail(tmp_path, removed):
    """This is the assertion that proves the guard works."""
    root = _workflow_with_filter_removed(tmp_path, removed)
    coverages, _ = analyse(root)
    unreachable = [c.pattern for c in coverages if not c.reachable]
    assert removed in unreachable


def test_cli_exits_nonzero_when_a_filter_is_missing(tmp_path, capsys):
    root = _workflow_with_filter_removed(tmp_path, "architecture.yaml")
    assert main(["--repo", str(root)]) == 1
    assert "architecture.yaml" in capsys.readouterr().out


def test_cli_exits_zero_on_the_real_repo(capsys):
    assert main(["--repo", str(REPO_ROOT)]) == 0
    assert "OK" in capsys.readouterr().out


# --- glob semantics -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "glob", "expected"),
    [
        ("tests/test_x.py", "tests/**", True),
        ("tests/deep/nested/test_x.py", "tests/**", True),
        ("testsuite/x.py", "tests/**", False),  # must respect the path boundary
        ("features.yaml", "features.yaml", True),
        ("features.schema.json", "features.yaml", False),
        ("src/eval_harness/scorers/a.py", "src/**", True),
        (".github/CODEOWNERS", ".github/**", True),
        (".github/CODEOWNERS", ".github/workflows/**", False),
    ],
)
def test_filter_matching_semantics(path, glob, expected):
    assert filter_matches(path, glob) is expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("features.yaml", "features.yaml"),
        ("architecture.yaml", "architecture.yaml"),
        ("tests/**", "tests/probe.py"),
        ("config/**", "config/probe.py"),
    ],
)
def test_sample_path_generation(pattern, expected):
    assert sample_path_for(pattern) == expected


def test_exact_patterns_yield_exactly_themselves():
    assert sample_paths_for("features.yaml") == ("features.yaml",)


def test_directory_patterns_probe_more_than_one_depth():
    """One probe is not enough — see the child-filter regression below."""
    samples = sample_paths_for("config/**")
    assert len(samples) > 1
    assert any("/" not in s[len("config/") :] for s in samples), "need a direct child probe"
    assert any(s.count("/") > 2 for s in samples), "need a deeper probe"


def test_a_narrowed_child_filter_does_not_cover_the_protected_tree(tmp_path):
    """The false GREEN found in review of PR #124.

    With a single `config/sample/probe.py` probe, the filter `config/sample/**` matched
    it and `config/**` was reported reachable — while a PR touching `config/other.yaml`
    ran no protected-path check at all. Requiring every probe to match rejects it.
    """
    text = (REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")
    mutated = text.replace('- "config/**"', '- "config/sample/**"')
    assert mutated != text, "config/** filter was not present to narrow"
    root = tmp_path / "repo"
    (root / GUARD_WORKFLOW.parent).mkdir(parents=True)
    (root / GUARD_WORKFLOW).write_text(mutated, encoding="utf-8")

    coverages, _ = analyse(root)
    assert "config/**" in [c.pattern for c in coverages if not c.reachable]


# --- the guard must actually be invoked ----------------------------------------------


def _workflow_text(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "repo"
    (root / GUARD_WORKFLOW.parent).mkdir(parents=True)
    (root / GUARD_WORKFLOW).write_text(text, encoding="utf-8")
    return root


def test_analyse_fails_closed_when_the_guard_is_not_invoked(tmp_path):
    """Deleting the guard job left every pattern looking "reachable" — a green tick for
    a guard that no longer exists, the precise failure this script exists to prevent."""
    text = (REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")
    without = "\n".join(line for line in text.splitlines() if "check_protected_changes.py" not in line)
    with pytest.raises(GuardNotInvokedError, match="does not run"):
        analyse(_workflow_text(tmp_path, without))


def test_a_commented_out_guard_does_not_count_as_invoked(tmp_path):
    """A bare substring search would pass here — this repo's workflows mention the
    script in comments, so the check must look for an executable `run:` step."""
    text = (REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")
    commented = text.replace(
        "      - run: python scripts/check_protected_changes.py",
        "      # - run: python scripts/check_protected_changes.py",
    )
    assert commented != text
    with pytest.raises(GuardNotInvokedError):
        analyse(_workflow_text(tmp_path, commented))


def test_cli_exits_nonzero_when_the_guard_is_not_invoked(tmp_path, capsys):
    text = (REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")
    without = "\n".join(line for line in text.splitlines() if "check_protected_changes.py" not in line)
    assert main(["--repo", str(_workflow_text(tmp_path, without))]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_guard_is_invoked_on_the_real_workflow():
    assert guard_is_invoked((REPO_ROOT / GUARD_WORKFLOW).read_text(encoding="utf-8")) is True


# --- workflow parsing ---------------------------------------------------------------


def test_extracts_only_pull_request_filters():
    """Filters under push/schedule must not be counted as pull_request coverage."""
    text = """
on:
  push:
    paths:
      - "should-not-count/**"
  pull_request:
    paths:
      - "counted/**"
      # a comment inside the list
      - "also-counted.yaml"
  workflow_dispatch:

jobs:
  x:
    runs-on: ubuntu-latest
"""
    assert extract_path_filters(text) == ["counted/**", "also-counted.yaml"]


def test_workflow_without_a_pull_request_trigger_yields_no_filters():
    assert extract_path_filters("on:\n  push:\n    branches: [main]\n") == []


def test_pull_request_without_a_paths_block_yields_no_filters():
    assert extract_path_filters("on:\n  pull_request:\n    branches: [main]\njobs: {}\n") == []


def test_missing_workflow_is_a_usage_error(tmp_path, capsys):
    assert main(["--repo", str(tmp_path)]) == 2


def test_a_catch_all_filter_without_the_guard_still_fails(tmp_path):
    """This used to be a *warning*, and that was the bug.

    A `**` filter makes every protected pattern look reachable, so the check reported OK
    for a workflow that runs no guard at all. It now raises instead.
    """
    root = tmp_path / "repo"
    (root / GUARD_WORKFLOW.parent).mkdir(parents=True)
    (root / GUARD_WORKFLOW).write_text('on:\n  pull_request:\n    paths:\n      - "**"\njobs: {}\n', encoding="utf-8")
    with pytest.raises(GuardNotInvokedError):
        analyse(root)


# --- reporting ----------------------------------------------------------------------


def test_json_output_is_byte_stable(capsys):
    main(["--repo", str(REPO_ROOT), "--json"])
    first = capsys.readouterr().out
    main(["--repo", str(REPO_ROOT), "--json"])
    assert capsys.readouterr().out == first


def test_json_output_reports_pass_and_every_pattern(capsys):
    main(["--repo", str(REPO_ROOT), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert {c["pattern"] for c in payload["coverage"]} == set(PROTECTED_PATTERNS)


def test_text_report_names_the_offending_pattern_and_the_fix():
    rendered = render_text([Coverage("architecture.yaml", "architecture.yaml", None)], ["src/**"])
    assert "architecture.yaml" in rendered
    assert "quality-gates.yml" in rendered, "the report must say where to fix it"


def test_text_report_is_affirmative_when_clean():
    rendered = render_text([Coverage("features.yaml", "features.yaml", "features.yaml")], ["features.yaml"])
    assert "OK" in rendered


def test_verbose_emits_per_pattern_debug(caplog):
    with caplog.at_level(logging.DEBUG, logger="check_guard_reachability"):
        analyse(REPO_ROOT)
    assert any("architecture.yaml" in r.getMessage() for r in caplog.records)
