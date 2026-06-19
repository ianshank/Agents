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


def test_reconstruct_nodeid_prefix_mismatch_with_file() -> None:
    # classname carries a different package prefix than the file path.
    nodeid = rg.reconstruct_nodeid("test_x.TestC", "test_y", file="tests/test_x.py")
    assert nodeid == "tests/test_x.py::TestC::test_y"


def test_reconstruct_nodeid_windows_separators() -> None:
    nodeid = rg.reconstruct_nodeid("tests.test_x", "test_y", file="tests\\test_x.py")
    assert nodeid == "tests/test_x.py::test_y"


def test_reconstruct_nodeid_no_module_segment_keeps_class_parts() -> None:
    # classname shares no segment with the file stem: keep Capitalised (class) parts.
    nodeid = rg.reconstruct_nodeid("weird.TestC", "test_y", file="tests/test_x.py")
    assert nodeid == "tests/test_x.py::TestC::test_y"


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


def test_create_baseline_worktree_bad_ref_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    monkeypatch.chdir(repo)
    with pytest.raises(rg.ConfigError):
        rg.create_baseline_worktree("no-such-ref-xyz")


# ---------------------------------------------------------------------------
# Tooling invocation (real ruff/pytest in isolated temp trees)
# ---------------------------------------------------------------------------


def test_run_ruff_reports_findings(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\n", encoding="utf-8")
    findings = rg.run_ruff(tmp_path, ["."], timeout=120)
    assert any(f.code == "F401" and f.path == "bad.py" for f in findings)


def test_run_ruff_raises_on_tool_error(tmp_path: Path) -> None:
    # A malformed ruff config makes ruff exit 2 (config error) rather than 0/1.
    (tmp_path / "ruff.toml").write_text('line-length = "not-an-int"\n', encoding="utf-8")
    (tmp_path / "x.py").write_text("y = 1\n", encoding="utf-8")
    with pytest.raises(rg.ConfigError):
        rg.run_ruff(tmp_path, ["."], timeout=120)


def test_run_pytest_collects_failures(tmp_path: Path) -> None:
    (tmp_path / "test_demo.py").write_text(
        "def test_a():\n    assert True\n\n\ndef test_b():\n    assert False\n",
        encoding="utf-8",
    )
    failures = rg.run_pytest(tmp_path, ["."], timeout=120)
    assert any("test_b" in f for f in failures)
    assert not any("test_a" in f for f in failures)
    # Temp junit report must not leak.
    assert not (tmp_path / ".regression_gate_junit.xml").exists()


def test_run_pytest_raises_on_collection_error(tmp_path: Path) -> None:
    # An un-importable test module makes pytest exit 2 (collection error), not 0/1.
    (tmp_path / "test_broken.py").write_text("import a_module_that_does_not_exist_xyz\n", encoding="utf-8")
    with pytest.raises(rg.ConfigError):
        rg.run_pytest(tmp_path, ["."], timeout=120)
    assert not (tmp_path / ".regression_gate_junit.xml").exists()


def test_relativise_joins_relative_paths_to_root(tmp_path: Path) -> None:
    # A ruff-style relative filename must resolve against root, not the process cwd.
    payload = json.dumps([{"filename": "pkg/mod.py", "code": "F401", "location": {"row": 1}}])
    findings = rg.parse_ruff_json(payload, root=tmp_path)
    assert {f.path for f in findings} == {"pkg/mod.py"}


def test_run_pytest_cleans_report_on_parse_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "test_demo.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")

    def boom(_payload: str) -> set[str]:
        raise rg.ConfigError("synthetic parse failure")

    monkeypatch.setattr(rg, "parse_junit_failures", boom)
    with pytest.raises(rg.ConfigError):
        rg.run_pytest(tmp_path, ["."], timeout=120)
    assert not (tmp_path / ".regression_gate_junit.xml").exists()


# ---------------------------------------------------------------------------
# Orchestration + CLI
# ---------------------------------------------------------------------------


def test_run_gate_diffs_trees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "base"
    base.mkdir()
    removed: list[Path] = []
    monkeypatch.setattr(rg, "create_baseline_worktree", lambda ref: base)
    monkeypatch.setattr(rg, "remove_baseline_worktree", lambda p: removed.append(p))

    pre = rg.LintFinding("a.py", "F401", 1)
    new = rg.LintFinding("a.py", "F811", 2)

    def fake_ruff(tree: Path, paths: list[str], *, timeout: int) -> set[rg.LintFinding]:
        return {pre} if tree == base else {pre, new}

    def fake_pytest(tree: Path, paths: list[str], *, timeout: int) -> set[str]:
        return set() if tree == base else {"t.py::test_new"}

    monkeypatch.setattr(rg, "run_ruff", fake_ruff)
    monkeypatch.setattr(rg, "run_pytest", fake_pytest)

    report = rg.run_gate(base_ref="HEAD", lint_paths=["src"], test_paths=["tests"], mode=rg.GateMode.BLOCK, timeout=10)
    assert report.passed is False
    assert {"file": "a.py", "code": "F811", "line": 2} in report.net_new_lint
    assert report.net_new_tests == ["t.py::test_new"]
    assert removed == [base]


def _passing_report() -> rg.GateReport:
    return rg.build_report(
        base_ref="HEAD",
        mode=rg.GateMode.BLOCK,
        baseline_lint=set(),
        current_lint=set(),
        baseline_tests=set(),
        current_tests=set(),
    )


def _failing_report() -> rg.GateReport:
    return rg.build_report(
        base_ref="HEAD",
        mode=rg.GateMode.BLOCK,
        baseline_lint=set(),
        current_lint={rg.LintFinding("a.py", "F811", 2)},
        baseline_tests=set(),
        current_tests={"t.py::test_new"},
    )


def test_main_passing_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rg, "run_gate", lambda **kw: _passing_report())
    report_path = tmp_path / "r.json"
    assert rg.main(["--report-path", str(report_path)]) == 0
    assert report_path.is_file()


def test_main_block_fails_on_net_new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rg, "run_gate", lambda **kw: _failing_report())
    assert rg.main(["--report-path", str(tmp_path / "r.json")]) == 1


def test_main_warn_does_not_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rg, "run_gate", lambda **kw: _failing_report())
    assert rg.main(["--mode", "warn", "--report-path", str(tmp_path / "r.json")]) == 0


def test_main_config_error_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**kw: object) -> rg.GateReport:
        raise rg.ConfigError("synthetic")

    monkeypatch.setattr(rg, "run_gate", boom)
    assert rg.main(["--report-path", str(tmp_path / "r.json")]) == 2
