#!/usr/bin/env python3
"""Tests for the charter-invariants gate (``scripts/check_charter_invariants.py``).

Mirrors ``test_check_charter_drift.py``: a "the real repo currently passes" sanity test
per check, plus synthetic ``tmp_path`` fixtures exercising each check's failure path.
"""

from __future__ import annotations

import json
from pathlib import Path

import check_charter_invariants as guard
import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Real-repo sanity checks (one per hard check)
# ---------------------------------------------------------------------------


def test_real_repo_mission_dirs_pass() -> None:
    assert guard.check_mission_dirs(_repo_root()) == []


def test_real_repo_agent_core_has_zero_deps() -> None:
    assert guard.check_agent_core_zero_deps(_repo_root()) == []


def test_real_repo_schema_version_single_sourced() -> None:
    assert guard.check_schema_version_single_source(_repo_root()) == []


def test_real_repo_coverage_floors_declared() -> None:
    assert guard.check_coverage_floors_declared(_repo_root()) == []


def test_real_repo_protected_path_label_matches() -> None:
    assert guard.check_protected_path_label(_repo_root()) == []


def test_protected_changes_missing_is_hard_finding(tmp_path: Path) -> None:
    findings = guard.check_protected_path_label(tmp_path)
    assert findings == [
        guard.Finding("protected_changes_missing", str(tmp_path / "scripts" / "check_protected_changes.py"), hard=True)
    ]


def test_approval_label_mismatch_is_hard_finding(tmp_path: Path) -> None:
    # A self-contained fake -- no _cli/eval_protected_paths imports needed, so this loads
    # cleanly via spec_from_file_location without touching the real scripts/ on sys.path.
    _write(tmp_path, "scripts/check_protected_changes.py", 'DEFAULT_APPROVAL_LABEL = "wrong-label"\n')
    findings = guard.check_protected_path_label(tmp_path)
    assert len(findings) == 1
    assert findings[0].hard and findings[0].kind == "approval_label_mismatch"
    assert "wrong-label" in findings[0].detail


def test_protected_changes_module_load_error_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/check_protected_changes.py", "raise RuntimeError('boom')\n")
    findings = guard.check_protected_path_label(tmp_path)
    assert len(findings) == 1
    assert findings[0].hard and findings[0].kind == "protected_changes_import_failed"
    assert "boom" in findings[0].detail


def test_matching_approval_label_is_clean(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "scripts/check_protected_changes.py",
        f'DEFAULT_APPROVAL_LABEL = "{guard.CHARTER_APPROVAL_LABEL}"\n',
    )
    assert guard.check_protected_path_label(tmp_path) == []


def test_real_repo_quality_gates_wired() -> None:
    assert guard.check_quality_gates_wired(_repo_root()) == []


def test_real_repo_interfaces_are_protocols() -> None:
    assert guard.check_protocol_interfaces(_repo_root()) == []


def test_real_repo_default_off_flags_hold() -> None:
    assert guard.check_default_off_flags(_repo_root()) == []


def test_real_repo_has_no_drift(capsys: pytest.CaptureFixture[str]) -> None:
    """End-to-end: the real repo's CLI exits 0 (warnings from the magic-number
    heuristic may still print, but no hard failure)."""
    assert guard.main([]) == 0


# ---------------------------------------------------------------------------
# check_mission_dirs
# ---------------------------------------------------------------------------


def test_missing_mission_dir_is_hard_finding(tmp_path: Path) -> None:
    for rel in guard._MISSION_DIRS:
        if rel != "scripts":
            (tmp_path / rel).mkdir(parents=True)
    findings = guard.check_mission_dirs(tmp_path)
    assert [f for f in findings if f.hard and f.detail == "scripts"]


# ---------------------------------------------------------------------------
# check_agent_core_zero_deps
# ---------------------------------------------------------------------------


def test_agent_core_with_runtime_deps_is_hard_finding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "agent-core/pyproject.toml",
        '[project]\nname = "x"\ndependencies = ["requests"]\n',
    )
    findings = guard.check_agent_core_zero_deps(tmp_path)
    assert findings and findings[0].hard
    assert findings[0].kind == "agent_core_has_runtime_deps"


def test_agent_core_with_no_deps_is_clean(tmp_path: Path) -> None:
    _write(tmp_path, "agent-core/pyproject.toml", '[project]\nname = "x"\n')
    assert guard.check_agent_core_zero_deps(tmp_path) == []


def test_agent_core_pyproject_missing_is_hard_finding(tmp_path: Path) -> None:
    findings = guard.check_agent_core_zero_deps(tmp_path)
    assert findings == [
        guard.Finding("agent_core_pyproject_missing", str(tmp_path / "agent-core" / "pyproject.toml"), hard=True)
    ]


# ---------------------------------------------------------------------------
# check_schema_version_single_source
# ---------------------------------------------------------------------------


def test_zero_schema_version_assignments_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/version.py", "OTHER = '1.0'\n")
    findings = guard.check_schema_version_single_source(tmp_path)
    assert findings and findings[0].hard


def test_duplicate_schema_version_assignments_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/version.py", "SCHEMA_VERSION = '1.0'\nSCHEMA_VERSION = '2.0'\n")
    findings = guard.check_schema_version_single_source(tmp_path)
    assert findings and findings[0].hard


def test_single_schema_version_assignment_is_clean(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/version.py", "SCHEMA_VERSION = '1.0'\n")
    assert guard.check_schema_version_single_source(tmp_path) == []


def test_version_py_missing_is_hard_finding(tmp_path: Path) -> None:
    findings = guard.check_schema_version_single_source(tmp_path)
    assert findings == [guard.Finding("version_py_missing", str(tmp_path / "src/eval_harness/version.py"), hard=True)]


def test_version_py_syntax_error_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/version.py", "SCHEMA_VERSION = (\n")  # unterminated
    findings = guard.check_schema_version_single_source(tmp_path)
    assert len(findings) == 1
    assert findings[0].hard and findings[0].kind == "version_py_unparseable"


# ---------------------------------------------------------------------------
# check_coverage_floors_declared
# ---------------------------------------------------------------------------


def test_missing_coverage_floor_is_hard_finding(tmp_path: Path) -> None:
    for rel in guard._PACKAGE_PYPROJECTS.values():
        _write(tmp_path, rel, "[tool.coverage.report]\nfail_under = 90\n")
    # scripts/.coveragerc deliberately omitted -> hard finding
    findings = guard.check_coverage_floors_declared(tmp_path)
    assert [f for f in findings if f.hard and "coveragerc" in f.detail]


def test_all_coverage_floors_declared_is_clean(tmp_path: Path) -> None:
    for rel in guard._PACKAGE_PYPROJECTS.values():
        _write(tmp_path, rel, "[tool.coverage.report]\nfail_under = 90\n")
    _write(tmp_path, "scripts/.coveragerc", "[report]\nfail_under = 85\n")
    assert guard.check_coverage_floors_declared(tmp_path) == []


def test_pyproject_present_without_floor_is_hard_finding(tmp_path: Path) -> None:
    for rel in guard._PACKAGE_PYPROJECTS.values():
        _write(tmp_path, rel, "[tool.coverage.report]\nfail_under = 90\n")
    # eval_harness's own pyproject.toml (root) present but missing the coverage section.
    _write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n")
    _write(tmp_path, "scripts/.coveragerc", "[report]\nfail_under = 85\n")
    findings = guard.check_coverage_floors_declared(tmp_path)
    assert findings == [guard.Finding("coverage_floor_missing", "eval_harness: pyproject.toml", hard=True)]


def test_coveragerc_present_without_fail_under_is_hard_finding(tmp_path: Path) -> None:
    for rel in guard._PACKAGE_PYPROJECTS.values():
        _write(tmp_path, rel, "[tool.coverage.report]\nfail_under = 90\n")
    _write(tmp_path, "scripts/.coveragerc", "[report]\nshow_missing = True\n")
    findings = guard.check_coverage_floors_declared(tmp_path)
    assert findings == [guard.Finding("coverage_floor_missing", "scripts/.coveragerc", hard=True)]


# ---------------------------------------------------------------------------
# check_quality_gates_wired
# ---------------------------------------------------------------------------


def test_gate_missing_from_workflow_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, ".github/workflows/quality-gates.yml", "steps:\n  - run: python scripts/check_size_budget.py\n")
    findings = guard.check_quality_gates_wired(tmp_path)
    missing = {f.detail for f in findings}
    assert "check_charter_drift.py" in missing
    assert "check_size_budget.py" not in missing


def test_all_gates_wired_is_clean(tmp_path: Path) -> None:
    body = "\n".join(f"  - run: python scripts/{s}" for s in guard._EXPECTED_GATE_SCRIPTS)
    _write(tmp_path, ".github/workflows/quality-gates.yml", f"steps:\n{body}\n")
    assert guard.check_quality_gates_wired(tmp_path) == []


def test_quality_gates_workflow_missing_is_hard_finding(tmp_path: Path) -> None:
    findings = guard.check_quality_gates_wired(tmp_path)
    assert findings == [
        guard.Finding(
            "quality_gates_workflow_missing", str(tmp_path / ".github/workflows/quality-gates.yml"), hard=True
        )
    ]


# ---------------------------------------------------------------------------
# check_protocol_interfaces
# ---------------------------------------------------------------------------


def _interfaces_body(protocol_base: str = "Protocol", scorer_base: str = "ABC") -> str:
    lines = [f"class {name}({protocol_base}): ...\n" for name in guard._PROTOCOL_INTERFACES]
    lines += [f"class {name}({scorer_base}): ...\n" for name in guard._ABC_INTERFACES]
    return "\n".join(lines)


def test_abc_interfaces_are_hard_findings(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/core/interfaces.py", _interfaces_body(protocol_base="ABC"))
    findings = guard.check_protocol_interfaces(tmp_path)
    assert len(findings) == len(guard._PROTOCOL_INTERFACES)
    assert all(f.hard and f.kind == "interface_not_protocol" for f in findings)


def test_scorer_as_protocol_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/core/interfaces.py", _interfaces_body(scorer_base="Protocol"))
    findings = guard.check_protocol_interfaces(tmp_path)
    assert findings == [guard.Finding("interface_not_abc", "Scorer(bases=['Protocol'])", hard=True)]


def test_protocol_interfaces_are_clean(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/core/interfaces.py", _interfaces_body())
    assert guard.check_protocol_interfaces(tmp_path) == []


def test_missing_interface_class_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/core/interfaces.py", "class Unrelated: ...\n")
    findings = guard.check_protocol_interfaces(tmp_path)
    assert {f.detail for f in findings if f.kind == "interface_class_missing"} == {
        *guard._PROTOCOL_INTERFACES,
        *guard._ABC_INTERFACES,
    }


def test_interfaces_py_missing_is_hard_finding(tmp_path: Path) -> None:
    findings = guard.check_protocol_interfaces(tmp_path)
    assert findings == [
        guard.Finding("interfaces_py_missing", str(tmp_path / "src/eval_harness/core/interfaces.py"), hard=True)
    ]


def test_interfaces_py_syntax_error_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/core/interfaces.py", "class Scorer(\n")  # unterminated
    findings = guard.check_protocol_interfaces(tmp_path)
    assert len(findings) == 1
    assert findings[0].hard and findings[0].kind == "interfaces_py_unparseable"


# ---------------------------------------------------------------------------
# check_default_off_flags
# ---------------------------------------------------------------------------


def test_fix_loop_enabled_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/fix_loop.py", "FIX_ENABLED: bool = True\n")
    _write(tmp_path, ".github/workflows/calibrated-merge-gate.yml", "ENABLE_CALIBRATED_AUTOMERGE\n")
    findings = guard.check_default_off_flags(tmp_path)
    assert [f for f in findings if f.kind == "fix_loop_not_disabled_by_default"]


def test_merge_gate_without_env_flag_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/fix_loop.py", "FIX_ENABLED: bool = False\n")
    _write(tmp_path, ".github/workflows/calibrated-merge-gate.yml", "no gate here\n")
    findings = guard.check_default_off_flags(tmp_path)
    assert [f for f in findings if f.kind == "auto_merge_flag_not_gated"]


def test_flags_off_and_gated_is_clean(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/fix_loop.py", "FIX_ENABLED: bool = False\n")
    _write(tmp_path, ".github/workflows/calibrated-merge-gate.yml", "if: vars.ENABLE_CALIBRATED_AUTOMERGE\n")
    assert guard.check_default_off_flags(tmp_path) == []


def test_fix_loop_missing_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, ".github/workflows/calibrated-merge-gate.yml", "ENABLE_CALIBRATED_AUTOMERGE\n")
    findings = guard.check_default_off_flags(tmp_path)
    assert {f.kind for f in findings} == {"fix_loop_missing"}


def test_calibrated_merge_gate_workflow_missing_is_hard_finding(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/fix_loop.py", "FIX_ENABLED: bool = False\n")
    findings = guard.check_default_off_flags(tmp_path)
    assert {f.kind for f in findings} == {"calibrated_merge_gate_workflow_missing"}


# ---------------------------------------------------------------------------
# check_magic_number_defaults (soft, non-blocking)
# ---------------------------------------------------------------------------


def test_bare_numeric_default_is_soft_warning(tmp_path: Path) -> None:
    _write(
        tmp_path, "src/eval_harness/thing.py", "class Thing:\n    def __init__(self, x: int = 1024):\n        pass\n"
    )
    findings = guard.check_magic_number_defaults(tmp_path)
    assert findings and all(not f.hard for f in findings)
    assert findings[0].kind == "possible_magic_number_default"


def test_config_class_default_is_not_flagged(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/eval_harness/thing.py",
        "class ThingConfig:\n    def __init__(self, x: int = 1024):\n        pass\n",
    )
    assert guard.check_magic_number_defaults(tmp_path) == []


def test_allowlisted_default_is_not_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/thing.py", "class Thing:\n    def __init__(self, x: int = 1):\n        pass\n")
    assert guard.check_magic_number_defaults(tmp_path) == []


def test_test_files_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/tests/test_thing.py", "def f(x=1024): pass\n")
    assert guard.check_magic_number_defaults(tmp_path) == []


def test_hundred_is_no_longer_allowlisted(tmp_path: Path) -> None:
    """100 is a plausible operational default (batch size/timeout/retry count) --
    allowlisting it would undermine the heuristic it's part of."""
    assert 100 not in guard._MAGIC_NUMBER_ALLOWLIST
    _write(tmp_path, "src/eval_harness/thing.py", "class Thing:\n    def __init__(self, x: int = 100):\n        pass\n")
    findings = guard.check_magic_number_defaults(tmp_path)
    assert findings and findings[0].detail.endswith("default=100")


def test_syntax_error_file_is_skipped_not_raised(tmp_path: Path) -> None:
    _write(tmp_path, "src/eval_harness/broken.py", "def f(x=1024\n")  # unterminated
    assert guard.check_magic_number_defaults(tmp_path) == []


def test_scan_roots_are_derived_from_mission_dirs(tmp_path: Path) -> None:
    """Reuses _MISSION_DIRS (the single source of truth) rather than a second,
    independently-maintained scan-root list -- covers a mission dir other than the
    two the heuristic originally hardcoded (src/eval_harness, agent-core/agent_core)."""
    _write(
        tmp_path,
        "flow-corpus/thing.py",
        "class Thing:\n    def __init__(self, x: int = 1024):\n        pass\n",
    )
    findings = guard.check_magic_number_defaults(tmp_path)
    assert any(f.detail.startswith("flow-corpus/") for f in findings)


# ---------------------------------------------------------------------------
# CLI: exit codes, --json
# ---------------------------------------------------------------------------


def test_cli_exits_1_on_hard_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_repo_root", lambda: tmp_path)
    assert guard.main([]) == 1


def test_cli_exits_2_on_usage_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def _boom(_root: Path) -> list[guard.Finding]:
        raise OSError("disk exploded")

    monkeypatch.setattr(guard, "run_all", _boom)
    assert guard.main([]) == guard.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err


def test_cli_json_output_is_valid(capsys: pytest.CaptureFixture[str]) -> None:
    guard.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert all({"kind", "detail", "hard"} <= set(item) for item in payload)


def test_run_all_sorts_hard_findings_first(tmp_path: Path) -> None:
    findings = guard.run_all(tmp_path)  # empty repo -> every dir/file missing
    assert findings
    hard_flags = [f.hard for f in findings]
    assert hard_flags == sorted(hard_flags, key=lambda h: not h)
