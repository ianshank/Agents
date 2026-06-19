#!/usr/bin/env python3
"""Tests for scripts/regression_gate.py — the net-new regression gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import regression_gate as rg

# ---------------------------------------------------------------------------
# Pure logic: ruff parsing (line-keyed identity)
# ---------------------------------------------------------------------------


def test_parse_ruff_json_is_line_keyed(tmp_path: Path) -> None:
    payload = json.dumps(
        [
            {"filename": str(tmp_path / "a.py"), "code": "F401", "location": {"row": 3}},
            {"filename": str(tmp_path / "a.py"), "code": "F401", "location": {"row": 9}},
        ]
    )
    findings = rg.parse_ruff_json(payload, root=tmp_path)
    # Two instances of one rule in one file at different lines => two findings.
    assert len(findings) == 2
    assert {f.line for f in findings} == {3, 9}
    assert all(f.path == "a.py" and f.code == "F401" for f in findings)


def test_parse_ruff_json_empty() -> None:
    assert rg.parse_ruff_json("", root=Path(".")) == set()
    assert rg.parse_ruff_json("[]", root=Path(".")) == set()


# ---------------------------------------------------------------------------
# Pure logic: junit nodeid reconstruction (incl. class-based tests)
# ---------------------------------------------------------------------------


def test_reconstruct_nodeid_function_with_file() -> None:
    nodeid = rg.reconstruct_nodeid("tests.test_x", "test_y", file="tests/test_x.py")
    assert nodeid == "tests/test_x.py::test_y"


def test_reconstruct_nodeid_class_based_with_file() -> None:
    nodeid = rg.reconstruct_nodeid("tests.test_x.TestC", "test_y", file="tests/test_x.py")
    assert nodeid == "tests/test_x.py::TestC::test_y"


def test_reconstruct_nodeid_class_based_fallback_no_file() -> None:
    # No 'file' attribute: trailing Capitalised segment is treated as the class.
    nodeid = rg.reconstruct_nodeid("tests.test_x.TestC", "test_y")
    assert nodeid == "tests/test_x.py::TestC::test_y"


def test_reconstruct_nodeid_function_fallback_no_file() -> None:
    nodeid = rg.reconstruct_nodeid("tests.test_x", "test_y")
    assert nodeid == "tests/test_x.py::test_y"


def test_parse_junit_failures_mixed() -> None:
    xml = """
    <testsuites><testsuite>
      <testcase classname="tests.test_x" name="test_ok" file="tests/test_x.py"/>
      <testcase classname="tests.test_x" name="test_bad" file="tests/test_x.py">
        <failure message="boom">trace</failure>
      </testcase>
      <testcase classname="tests.test_x.TestC" name="test_err" file="tests/test_x.py">
        <error message="kaboom">trace</error>
      </testcase>
    </testsuite></testsuites>
    """
    failures = rg.parse_junit_failures(xml)
    assert failures == {
        "tests/test_x.py::test_bad",
        "tests/test_x.py::TestC::test_err",
    }


def test_parse_junit_failures_empty() -> None:
    assert rg.parse_junit_failures("") == set()


# ---------------------------------------------------------------------------
# Pure logic: net-new diff + report
# ---------------------------------------------------------------------------


def test_compute_net_new_blocks_only_new() -> None:
    baseline = {"a", "b"}
    current = {"a", "b", "c"}
    assert rg.compute_net_new(baseline, current) == ["c"]


def test_compute_net_new_preexisting_does_not_block() -> None:
    baseline = {"a", "b"}
    current = {"a", "b"}
    assert rg.compute_net_new(baseline, current) == []


def test_build_report_passed_when_no_net_new() -> None:
    f = rg.LintFinding("a.py", "F401", 1)
    report = rg.build_report(
        base_ref="HEAD",
        mode=rg.GateMode.BLOCK,
        baseline_lint={f},
        current_lint={f},
        baseline_tests={"tests/test_x.py::test_a"},
        current_tests={"tests/test_x.py::test_a"},
    )
    assert report.passed is True
    assert report.net_new_lint == []
    assert report.net_new_tests == []


def test_build_report_flags_net_new() -> None:
    old = rg.LintFinding("a.py", "F401", 1)
    new = rg.LintFinding("a.py", "F811", 5)
    report = rg.build_report(
        base_ref="HEAD",
        mode=rg.GateMode.BLOCK,
        baseline_lint={old},
        current_lint={old, new},
        baseline_tests=set(),
        current_tests={"tests/test_x.py::test_new_fail"},
    )
    assert report.passed is False
    assert report.net_new_lint == [{"file": "a.py", "code": "F811", "line": 5}]
    assert report.net_new_tests == ["tests/test_x.py::test_new_fail"]


# ---------------------------------------------------------------------------
# Report conforms to its JSON schema
# ---------------------------------------------------------------------------


def test_report_conforms_to_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = Path(__file__).resolve().parent.parent / "scripts" / "regression_report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    report = rg.build_report(
        base_ref="HEAD",
        mode=rg.GateMode.BLOCK,
        baseline_lint=set(),
        current_lint={rg.LintFinding("a.py", "F401", 2)},
        baseline_tests=set(),
        current_tests={"tests/test_x.py::test_a"},
    )
    document = json.loads(report.to_json())
    jsonschema.Draft202012Validator(schema).validate(document)


# ---------------------------------------------------------------------------
# Baseline isolation: worktree (not stash) — no untracked leakage
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_baseline_worktree_isolates_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    (repo / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(["add", "tracked.txt"], repo)
    _git(["commit", "-m", "initial"], repo)
    # An untracked file that 'git stash' would leak but a worktree must not.
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    monkeypatch.chdir(repo)
    baseline = rg.create_baseline_worktree("HEAD")
    try:
        assert (baseline / "tracked.txt").is_file()
        assert not (baseline / "untracked.txt").exists()
    finally:
        rg.remove_baseline_worktree(baseline)
    assert not baseline.exists()
