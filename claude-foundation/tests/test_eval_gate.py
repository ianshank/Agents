from __future__ import annotations

import json
from pathlib import Path

from foundation_tools import eval_gate as eg


def _write_grading(plugin_tree: Path, cases: list[dict[str, object]]) -> None:
    grading = plugin_tree / "skills" / "hello" / "evals" / "grading.json"
    grading.write_text(json.dumps({"skill": "hello", "cases": cases}), encoding="utf-8")


def test_no_grading_passes_by_default_but_fails_release(plugin_tree: Path) -> None:
    assert eg.gate_tree(plugin_tree, require_grading=False) == []
    findings = eg.gate_tree(plugin_tree, require_grading=True)
    assert any("no grading.json" in f for f in findings)


def test_all_cases_pass(plugin_tree: Path) -> None:
    _write_grading(plugin_tree, [{"id": f"case-{i}", "passed": True} for i in range(3)])
    assert eg.gate_tree(plugin_tree, require_grading=True) == []


def test_failed_case_is_reported_with_evidence(plugin_tree: Path) -> None:
    _write_grading(
        plugin_tree,
        [
            {"id": "case-0", "passed": True},
            {"id": "case-1", "passed": False, "evidence": "assertion 2 unmet"},
            {"id": "case-2", "passed": True},
        ],
    )
    findings = eg.gate_tree(plugin_tree, require_grading=True)
    assert findings == ["hello: case 'case-1' FAILED — assertion 2 unmet"]


def test_ungraded_case_is_reported(plugin_tree: Path) -> None:
    _write_grading(plugin_tree, [{"id": "case-0", "passed": True}])
    findings = eg.gate_tree(plugin_tree, require_grading=True)
    assert any("case 'case-1' has no grading result" in f for f in findings)
    assert any("case 'case-2' has no grading result" in f for f in findings)


def test_unreadable_files_are_findings(plugin_tree: Path) -> None:
    grading = plugin_tree / "skills" / "hello" / "evals" / "grading.json"
    grading.write_text("{broken", encoding="utf-8")
    assert any(
        "unreadable grading.json" in f for f in eg.gate_tree(plugin_tree, require_grading=True)
    )
    evals = plugin_tree / "skills" / "hello" / "evals" / "evals.json"
    evals.write_text("{broken", encoding="utf-8")
    assert any(
        "unreadable evals.json" in f for f in eg.gate_tree(plugin_tree, require_grading=True)
    )


def test_missing_skills_dir_and_cli(plugin_tree: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert eg.main(["--root", str(plugin_tree)]) == 0
    _write_grading(plugin_tree, [{"id": "case-0", "passed": False}])
    assert eg.main(["--root", str(plugin_tree), "--require-grading"]) == 1
    assert "EVAL GATE FAILED" in capsys.readouterr().out
    assert eg.main(["--root", str(plugin_tree / "nope")]) == 2
    empty = plugin_tree / "empty"
    empty.mkdir()
    assert any("no skills directory" in f for f in eg.gate_tree(empty, require_grading=False))
