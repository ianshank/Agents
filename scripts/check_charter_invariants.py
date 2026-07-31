#!/usr/bin/env python3
"""CI guard: mechanically re-check a battery of docs/CHARTER.md's claims against the code.

``check_charter_drift.py`` verifies the charter's markdown *links* resolve, but says
nothing about whether the claims those links back up are still true — that gap is why
``docs/CHARTER_ALIGNMENT_AUDIT.md`` had to be produced by hand (a multi-agent audit) rather
than caught in CI. This guard encodes the subset of that audit's checks that are cheap and
reliable to automate: existence checks, single-source-of-truth checks, and structural-type
checks, each cited back to the charter section it verifies. Checks that cannot be proven
mechanically (e.g. "no magic numbers" in general) get a best-effort heuristic reported as a
non-blocking warning instead of a hard gate — see :data:`Finding.hard`.

  python scripts/check_charter_invariants.py            # human-readable report
  python scripts/check_charter_invariants.py --json     # machine-readable report

Exit codes:
    0 - every hard check passed (warnings may still be printed)
    1 - at least one hard check failed
    2 - configuration / usage error
"""

from __future__ import annotations

import argparse
import ast
import configparser
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import tomllib
from _cli import configure_logging

logger = logging.getLogger(__name__)

EXIT_USAGE_ERROR = 2

# The charter's own documented approval-label string (§4, "Eval integrity"). Checked
# against check_protected_changes.DEFAULT_APPROVAL_LABEL below, not restated as separate
# behavior — this constant exists only so a drift between the two is a diff, not a re-read.
CHARTER_APPROVAL_LABEL = "eval-change-approved"

# Mission packages (charter §2) + the two supporting directories it also names.
_MISSION_DIRS = (
    "src/eval_harness",
    "agent-core",
    "behavioral-regression",
    "flow-corpus",
    "flow-protocol",
    "scripts",
    "skills",
)

# Package -> its pyproject.toml relative to repo root, for coverage-floor + deps checks.
_PACKAGE_PYPROJECTS = {
    "eval_harness": "pyproject.toml",
    "agent-core": "agent-core/pyproject.toml",
    "behavioral-regression": "behavioral-regression/pyproject.toml",
    "flow-corpus": "flow-corpus/pyproject.toml",
    "flow-protocol": "flow-protocol/pyproject.toml",
}

# Gate scripts the charter's quality-gates invariant (§4.6) names; each must still appear
# as a step in the CI workflow.
_EXPECTED_GATE_SCRIPTS = (
    "check_charter_drift.py",
    "check_charter_invariants.py",
    "check_size_budget.py",
    "check_protected_changes.py",
    "regression_gate.py",
)

# Interfaces that must be typing.Protocol (charter §4 invariant 3), by class name.
_PROTOCOL_INTERFACES = ("Scorer", "DatasetSource", "TargetRunner", "ResultSink", "Judge")

# Numeric literals excluded from the magic-number heuristic: common non-"operational-value"
# constants (identity/sentinel numbers), not charter violations to flag. int/float equality
# (0 == 0.0) means each value here also excludes its float/int counterpart.
_MAGIC_NUMBER_ALLOWLIST = {0, 1, -1, 2, 100}


@dataclass(frozen=True)
class Finding:
    """One invariant observation. ``hard`` findings gate CI; others are warnings."""

    kind: str
    detail: str
    hard: bool


def _repo_root() -> Path:
    """Repo root (parent of the ``scripts/`` directory holding this file)."""
    return Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------- individual checks


def check_mission_dirs(root: Path) -> list[Finding]:
    """Charter §2: the 5 packages + scripts/ + skills/ still exist."""
    findings = []
    for rel in _MISSION_DIRS:
        if not (root / rel).is_dir():
            findings.append(Finding("mission_dir_missing", rel, hard=True))
    return findings


def check_agent_core_zero_deps(root: Path) -> list[Finding]:
    """Charter §2: agent-core has zero runtime dependencies."""
    path = root / "agent-core" / "pyproject.toml"
    if not path.is_file():
        return [Finding("agent_core_pyproject_missing", str(path), hard=True)]
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if deps:
        return [Finding("agent_core_has_runtime_deps", f"dependencies={deps!r}", hard=True)]
    return []


def check_schema_version_single_source(root: Path) -> list[Finding]:
    """Charter §4 invariant 2: SCHEMA_VERSION is single-sourced in version.py."""
    path = root / "src/eval_harness/version.py"
    if not path.is_file():
        return [Finding("version_py_missing", str(path), hard=True)]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignments = [
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION"
    ]
    if len(assignments) != 1:
        return [
            Finding(
                "schema_version_not_single_sourced",
                f"found {len(assignments)} SCHEMA_VERSION assignment(s) in {path}",
                hard=True,
            )
        ]
    return []


def check_coverage_floors_declared(root: Path) -> list[Finding]:
    """Charter §4 invariant 6: every package + scripts/ declares a coverage floor.

    Existence only — the actual numbers are each package's own concern and restating
    them here would itself become a second source of truth to keep in sync.
    """
    findings = []
    for name, rel in _PACKAGE_PYPROJECTS.items():
        path = root / rel
        if not path.is_file():
            findings.append(Finding("pyproject_missing", f"{name}: {rel}", hard=True))
            continue
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        floor = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
        if floor is None:
            findings.append(Finding("coverage_floor_missing", f"{name}: {rel}", hard=True))

    coveragerc = root / "scripts/.coveragerc"
    if not coveragerc.is_file():
        findings.append(Finding("coverage_floor_missing", "scripts/.coveragerc", hard=True))
    else:
        parser = configparser.ConfigParser()
        parser.read(coveragerc)
        if not parser.has_option("report", "fail_under"):
            findings.append(Finding("coverage_floor_missing", "scripts/.coveragerc", hard=True))
    return findings


def check_protected_path_label(root: Path) -> list[Finding]:
    """Charter §4 'Eval integrity': the approval label matches the charter's documented one."""
    sys.path.insert(0, str(root / "scripts"))
    try:
        import check_protected_changes as guard
    except ImportError as exc:
        return [Finding("protected_changes_import_failed", str(exc), hard=True)]
    if guard.DEFAULT_APPROVAL_LABEL != CHARTER_APPROVAL_LABEL:
        return [
            Finding(
                "approval_label_mismatch",
                f"check_protected_changes.DEFAULT_APPROVAL_LABEL={guard.DEFAULT_APPROVAL_LABEL!r} "
                f"!= charter's {CHARTER_APPROVAL_LABEL!r}",
                hard=True,
            )
        ]
    return []


def check_quality_gates_wired(root: Path) -> list[Finding]:
    """Charter §4 invariant 6: the named gate scripts still run in CI."""
    path = root / ".github/workflows/quality-gates.yml"
    if not path.is_file():
        return [Finding("quality_gates_workflow_missing", str(path), hard=True)]
    text = path.read_text(encoding="utf-8")
    findings = []
    for script in _EXPECTED_GATE_SCRIPTS:
        if script not in text:
            findings.append(Finding("gate_not_wired", script, hard=True))
    return findings


def check_protocol_interfaces(root: Path) -> list[Finding]:
    """Charter §4 invariant 3: Judge/Scorer/Sink/Dataset/Target are typing.Protocol.

    Guards against regressing the ABC -> Protocol fix back to abc.ABC.
    """
    path = root / "src/eval_harness/core/interfaces.py"
    if not path.is_file():
        return [Finding("interfaces_py_missing", str(path), hard=True)]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in _PROTOCOL_INTERFACES:
            base_names = [b.id for b in node.bases if isinstance(b, ast.Name)]
            seen[node.name] = base_names
    findings = []
    for name in _PROTOCOL_INTERFACES:
        bases = seen.get(name)
        if bases is None:
            findings.append(Finding("interface_class_missing", name, hard=True))
        elif "Protocol" not in bases:
            findings.append(Finding("interface_not_protocol", f"{name}(bases={bases})", hard=True))
    return findings


def check_default_off_flags(root: Path) -> list[Finding]:
    """Charter §3: auto-fix loop disabled, auto-merge off by default (grep-based)."""
    findings = []

    fix_loop = root / "scripts/fix_loop.py"
    if not fix_loop.is_file():
        findings.append(Finding("fix_loop_missing", str(fix_loop), hard=True))
    elif not re.search(r"FIX_ENABLED\s*:?\s*(?:bool\s*)?=\s*False", fix_loop.read_text(encoding="utf-8")):
        findings.append(Finding("fix_loop_not_disabled_by_default", str(fix_loop), hard=True))

    merge_gate = root / ".github/workflows/calibrated-merge-gate.yml"
    if not merge_gate.is_file():
        findings.append(Finding("calibrated_merge_gate_workflow_missing", str(merge_gate), hard=True))
    elif "ENABLE_CALIBRATED_AUTOMERGE" not in merge_gate.read_text(encoding="utf-8"):
        findings.append(Finding("auto_merge_flag_not_gated", str(merge_gate), hard=True))

    return findings


def _is_config_class(node: ast.ClassDef) -> bool:
    return node.name.endswith("Config")


def check_magic_number_defaults(root: Path) -> list[Finding]:
    """Charter §4 invariant 5 (heuristic, non-blocking): flag bare numeric literal
    defaults on non-``__init__``-of-``*Config`` functions, outside tests. A proxy for
    "no hard-coded numeric defaults at call sites" — not a full proof, since a
    reasonable proxy is the best that's mechanically checkable here.
    """
    findings: list[Finding] = []
    roots = [root / "src" / "eval_harness", root / "agent-core" / "agent_core"]
    for scan_root in roots:
        if not scan_root.is_dir():
            continue
        for path in sorted(scan_root.rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            class_stack: list[ast.ClassDef] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_stack.append(node)
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                enclosing = next((c for c in reversed(class_stack) if node in ast.walk(c)), None)
                if enclosing is not None and _is_config_class(enclosing):
                    continue  # *Config classes ARE the documented-default source
                defaults = list(node.args.defaults) + list(node.args.kw_defaults)
                for default in defaults:
                    if (
                        isinstance(default, ast.Constant)
                        and isinstance(default.value, (int, float))
                        and not isinstance(default.value, bool)
                        and default.value not in _MAGIC_NUMBER_ALLOWLIST
                    ):
                        rel = path.relative_to(root)
                        findings.append(
                            Finding(
                                "possible_magic_number_default",
                                f"{rel}::{node.name} default={default.value!r}",
                                hard=False,
                            )
                        )
    return findings


_CHECKS = (
    check_mission_dirs,
    check_agent_core_zero_deps,
    check_schema_version_single_source,
    check_coverage_floors_declared,
    check_protected_path_label,
    check_quality_gates_wired,
    check_protocol_interfaces,
    check_default_off_flags,
    check_magic_number_defaults,
)


def run_all(root: Path) -> list[Finding]:
    """Run every registered check and return all findings, sorted (hard first)."""
    findings: list[Finding] = []
    for check in _CHECKS:
        findings.extend(check(root))
    return sorted(findings, key=lambda f: (not f.hard, f.kind, f.detail))


def _report(findings: list[Finding]) -> None:
    """Print a human-readable summary of findings."""
    hard = [f for f in findings if f.hard]
    warnings = [f for f in findings if not f.hard]
    for f in warnings:
        print(f"[warn] {f.kind}: {f.detail}")
    if hard:
        print(f"charter-invariants: FAIL - {len(hard)} broken invariant(s):")
        for f in hard:
            print(f"  {f.kind}: {f.detail}")
    else:
        print(f"charter-invariants: OK - all checks passed ({len(warnings)} warning(s)).")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Re-check docs/CHARTER.md's claims against the code.")
    parser.add_argument("--json", action="store_true", help="Emit a JSON report on stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the charter-invariants check and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    root = _repo_root()
    try:
        findings = run_all(root)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        logger.error("cannot run charter-invariants checks: %s", exc)
        print(f"charter-invariants: usage error — {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    hard_failures = [f for f in findings if f.hard]
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2, sort_keys=True))
    else:
        _report(findings)

    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
