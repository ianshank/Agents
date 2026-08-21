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
import importlib.util
import json
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from _cli import configure_logging
from check_guard_reachability import script_is_invoked

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
    "check_guard_reachability.py",
    "check_protected_changes.py",
    "regression_gate.py",
)

# Interfaces that must be typing.Protocol (charter §4 invariant 3), by class name. Scorer
# Scorer was historically in _ABC_INTERFACES because Protocol.__init__ did not
# reliably propagate on Python 3.10. With the floor raised to >=3.11 (ADR 0034),
# the fix is universally available and Scorer is now a Protocol like the rest.
_PROTOCOL_INTERFACES = ("DatasetSource", "TargetRunner", "ResultSink", "Judge", "Scorer", "StateAdapter")
_ABC_INTERFACES: tuple[str, ...] = ()

# Numeric literals excluded from the magic-number heuristic: pure identity/sentinel values
# (0, empty/singular counts, sign flip). Deliberately does NOT include round operational
# numbers like 100 (a plausible batch size / timeout / retry count) — that's exactly the
# class of value this heuristic exists to catch, so allowlisting it would undermine the
# check. int/float equality (0 == 0.0) means each entry also excludes its float counterpart.
_MAGIC_NUMBER_ALLOWLIST = {0, 1, -1, 2}

# Tenacity retry-decorator callables whose numeric arguments are exactly the class of
# magic-number violation invariant 5 targets, but that were invisible to
# check_magic_number_defaults' original scan: it only ever inspected
# node.args.defaults/kw_defaults (function *signature* defaults), never the
# args/keywords of a Call expression inside a decorator like
# ``@retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(5))``.
# Found via a 2026-08-17 peer review of OpenAIJudge.evaluate, which carried exactly
# that violation undetected. The only tenacity callables this codebase actually uses.
_RETRY_DECORATOR_CALLABLES = {"retry", "wait_exponential", "wait_fixed", "stop_after_attempt"}


@dataclass(frozen=True)
class Finding:
    """One invariant observation. ``hard`` findings gate CI; others are warnings."""

    kind: str
    detail: str
    hard: bool


def _repo_root() -> Path:
    """Repo root (parent of the ``scripts/`` directory holding this file)."""
    return Path(__file__).resolve().parent.parent


def _extract_toml_section(text: str, section: str) -> str:
    """Return the raw body of a top-level TOML ``[section]`` (up to the next
    top-level header or EOF), or ``""`` if the section is absent.

    Deliberately not a full TOML parser: even though the floor is now 3.11+ (ADR
    0034), where stdlib ``tomllib`` is available, switching this existing regex
    scanner to real TOML parsing is a separate, untested-here change — the
    pyproject.toml files this reads are simple and well-formed, so a
    section-scoped regex remains sufficient without it.
    """
    pattern = re.compile(rf"^\[{re.escape(section)}\]\s*$(.*?)(?=^\[|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1) if match else ""


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
        return [Finding("agent_core_pyproject_missing", path.as_posix(), hard=True)]
    project_section = _extract_toml_section(path.read_text(encoding="utf-8"), "project")
    match = re.search(r"^\s*dependencies\s*=\s*\[(.*?)\]", project_section, re.MULTILINE | re.DOTALL)
    if match and match.group(1).strip():
        return [Finding("agent_core_has_runtime_deps", f"dependencies=[{match.group(1).strip()}]", hard=True)]
    return []


def check_schema_version_single_source(root: Path) -> list[Finding]:
    """Charter §4 invariant 2: SCHEMA_VERSION is single-sourced in version.py."""
    path = root / "src/eval_harness/version.py"
    if not path.is_file():
        return [Finding("version_py_missing", path.as_posix(), hard=True)]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [Finding("version_py_unparseable", f"{path.as_posix()}: {exc}", hard=True)]
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
                f"found {len(assignments)} SCHEMA_VERSION assignment(s) in {path.as_posix()}",
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
        section = _extract_toml_section(path.read_text(encoding="utf-8"), "tool.coverage.report")
        if "fail_under" not in section:
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
    """Charter §4 'Eval integrity': the approval label matches the charter's documented one.

    Loads ``check_protected_changes.py`` as an isolated module via
    ``importlib.util.spec_from_file_location`` rather than mutating ``sys.path`` /
    ``sys.modules`` (the previous approach): the test suite's ``conftest.py`` already
    puts the real ``scripts/`` on ``sys.path``, so a plain ``import`` would hit
    Python's module cache and silently ignore a ``tmp_path``-based synthetic root,
    making the failure branches below untestable.
    """
    path = root / "scripts" / "check_protected_changes.py"
    if not path.is_file():
        return [Finding("protected_changes_missing", path.as_posix(), hard=True)]
    spec = importlib.util.spec_from_file_location("_check_protected_changes_probe", path)
    if spec is None or spec.loader is None:
        return [Finding("protected_changes_import_failed", f"cannot load spec for {path.as_posix()}", hard=True)]
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # any load failure (syntax error, missing import, ...) is itself the finding
        return [Finding("protected_changes_import_failed", f"{path.as_posix()}: {exc}", hard=True)]
    label = getattr(module, "DEFAULT_APPROVAL_LABEL", None)
    if label != CHARTER_APPROVAL_LABEL:
        return [
            Finding(
                "approval_label_mismatch",
                f"check_protected_changes.DEFAULT_APPROVAL_LABEL={label!r} != charter's {CHARTER_APPROVAL_LABEL!r}",
                hard=True,
            )
        ]
    return []


def check_quality_gates_wired(root: Path) -> list[Finding]:
    """Charter §4 invariant 6: the named gate scripts still *run* in CI.

    Deliberately not a substring search. This workflow comments on its own gate scripts
    extensively, so ``script in text`` is satisfied by a comment describing a gate that
    was deleted — a wiring check that passes for unwired gates. ``script_is_invoked``
    requires the name inside an executable ``run:`` step, and is shared with
    ``check_guard_reachability`` so "wired into CI" has one definition.
    """
    path = root / ".github/workflows/quality-gates.yml"
    if not path.is_file():
        return [Finding("quality_gates_workflow_missing", path.as_posix(), hard=True)]
    text = path.read_text(encoding="utf-8")
    findings = []
    for script in _EXPECTED_GATE_SCRIPTS:
        if not script_is_invoked(text, script):
            findings.append(Finding("gate_not_wired", script, hard=True))
    return findings


def check_protocol_interfaces(root: Path) -> list[Finding]:
    """Charter §4 invariant 3: Judge/Sink/Dataset/Target are typing.Protocol; Scorer
    stays abc.ABC (see core/interfaces.py's module docstring for why).

    Guards against regressing the ABC -> Protocol fix, and against Scorer drifting
    to Protocol again (the confirmed-broken pattern on Python 3.10).
    """
    path = root / "src/eval_harness/core/interfaces.py"
    if not path.is_file():
        return [Finding("interfaces_py_missing", path.as_posix(), hard=True)]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [Finding("interfaces_py_unparseable", f"{path.as_posix()}: {exc}", hard=True)]
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in (*_PROTOCOL_INTERFACES, *_ABC_INTERFACES):
            base_names = [b.id for b in node.bases if isinstance(b, ast.Name)]
            seen[node.name] = base_names
    findings = []
    for name in _PROTOCOL_INTERFACES:
        bases = seen.get(name)
        if bases is None:
            findings.append(Finding("interface_class_missing", name, hard=True))
        elif "Protocol" not in bases:
            findings.append(Finding("interface_not_protocol", f"{name}(bases={bases})", hard=True))
    for name in _ABC_INTERFACES:
        bases = seen.get(name)
        if bases is None:
            findings.append(Finding("interface_class_missing", name, hard=True))
        elif "ABC" not in bases:
            findings.append(Finding("interface_not_abc", f"{name}(bases={bases})", hard=True))
    return findings


def check_default_off_flags(root: Path) -> list[Finding]:
    """Charter §3: auto-fix loop disabled, auto-merge off by default (grep-based)."""
    findings = []

    fix_loop = root / "scripts/fix_loop.py"
    if not fix_loop.is_file():
        findings.append(Finding("fix_loop_missing", fix_loop.as_posix(), hard=True))
    elif not re.search(r"FIX_ENABLED\s*:?\s*(?:bool\s*)?=\s*False", fix_loop.read_text(encoding="utf-8")):
        findings.append(Finding("fix_loop_not_disabled_by_default", fix_loop.as_posix(), hard=True))

    merge_gate = root / ".github/workflows/calibrated-merge-gate.yml"
    if not merge_gate.is_file():
        findings.append(Finding("calibrated_merge_gate_workflow_missing", merge_gate.as_posix(), hard=True))
    elif "ENABLE_CALIBRATED_AUTOMERGE" not in merge_gate.read_text(encoding="utf-8"):
        findings.append(Finding("auto_merge_flag_not_gated", merge_gate.as_posix(), hard=True))

    return findings


def _is_config_class(node: ast.ClassDef) -> bool:
    return node.name.endswith("Config")


def _is_magic_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value not in _MAGIC_NUMBER_ALLOWLIST


def _retry_call_magic_numbers(node: ast.AST, path: Path, root: Path) -> list[Finding]:
    """Bare numeric literals passed to a tenacity retry-decorator call.

    ``check_magic_number_defaults``'s original scan only ever inspected
    ``node.args.defaults``/``kw_defaults`` (function *signature* defaults), never the
    ``args``/``keywords`` of a ``Call`` expression inside a decorator like
    ``@retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(5))`` — a real
    gap found via a 2026-08-17 peer review of ``OpenAIJudge.evaluate``, which carried
    exactly that violation undetected.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return []
    if node.func.id not in _RETRY_DECORATOR_CALLABLES:
        return []
    literals = list(node.args) + [kw.value for kw in node.keywords]
    rel = path.relative_to(root).as_posix()
    return [
        Finding(
            "possible_magic_number_default",
            f"{rel}:{node.lineno}::{node.func.id}() literal={arg.value!r}",
            hard=False,
        )
        for arg in literals
        if isinstance(arg, ast.Constant) and _is_magic_number(arg.value)
    ]


def check_magic_number_defaults(root: Path) -> list[Finding]:
    """Charter §4 invariant 5 (heuristic, non-blocking): flag bare numeric literal
    defaults on non-``__init__``-of-``*Config`` functions, outside tests, AND bare
    numeric literals passed to a tenacity retry-decorator call (``retry``,
    ``wait_exponential``, ``wait_fixed``, ``stop_after_attempt`` —
    :data:`_RETRY_DECORATOR_CALLABLES`, see :func:`_retry_call_magic_numbers`). A proxy
    for "no hard-coded numeric defaults at call sites" — not a full proof, since a
    reasonable proxy is the best that's mechanically checkable here.
    """
    findings: list[Finding] = []
    # Reuse _MISSION_DIRS (the module's single source of truth for "packages the charter
    # applies to") rather than a second, independently-maintained list -- a prior version
    # of this scan hardcoded only 2 of the 7 mission dirs here, silently exempting
    # behavioral-regression/flow-corpus/flow-protocol/scripts from this heuristic.
    roots = [root / d for d in _MISSION_DIRS if (root / d).is_dir()]
    for scan_root in roots:
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
                findings.extend(_retry_call_magic_numbers(node, path, root))
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                enclosing = next((c for c in reversed(class_stack) if node in ast.walk(c)), None)
                if enclosing is not None and _is_config_class(enclosing):
                    continue  # *Config classes ARE the documented-default source
                defaults = list(node.args.defaults) + list(node.args.kw_defaults)
                for default in defaults:
                    if isinstance(default, ast.Constant) and _is_magic_number(default.value):
                        # ``.as_posix()`` so the detail is portable: on Windows a bare
                        # ``relative_to`` renders ``flow-corpus\thing.py``, which breaks any
                        # consumer matching on ``/`` (and differs from Linux CI's output).
                        rel = path.relative_to(root).as_posix()
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
    except (OSError, ValueError) as exc:
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
