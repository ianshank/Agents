#!/usr/bin/env python3
"""Regression gate — block only *net-new* lint/test failures versus a baseline ref.

The absolute gates already in CI (``ruff``, ``mypy``, ``pytest --cov``) answer the
question "is the tree healthy in absolute terms?". This gate answers a different,
complementary question: "did *this change* introduce anything that was not already
broken at the baseline?".

It works by materialising an **isolated** baseline of the baseline ref via
``git worktree add --detach`` (never ``git stash``, which leaks untracked files),
running the same lint + offline test commands in both the working tree and the
baseline, and reporting only the findings present now but absent at the baseline.

Only the offline, deterministic test suite is ever executed here — never the
live-judge / Langfuse-backed evals, which are non-deterministic and would make the
diff chase noise.

Exit codes:
    0 – no net-new findings (or ``--mode warn``)
    1 – net-new findings detected (``--mode block``)
    2 – configuration / tooling error
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults (no hard-coded magic scattered through the body — tune via CLI)
# ---------------------------------------------------------------------------

REPORT_SCHEMA_VERSION: str = "1.0"
DEFAULT_BASE_REF: str = "HEAD"
DEFAULT_LINT_PATHS: tuple[str, ...] = ("src", "tests")
DEFAULT_TEST_PATHS: tuple[str, ...] = ("tests",)
DEFAULT_TIMEOUT: int = 900
DEFAULT_REPORT_PATH: str = "regression_report.json"


class GateMode:
    """Enforcement modes for the gate."""

    BLOCK = "block"
    WARN = "warn"
    ALL = (BLOCK, WARN)


class ConfigError(RuntimeError):
    """Raised on tooling / environment errors that map to exit code 2."""


# ---------------------------------------------------------------------------
# Finding identities (pure, unit-testable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class LintFinding:
    """A single ruff finding, keyed by (path, rule, line).

    Line-keyed so two instances of the same rule in one file are two findings
    rather than collapsing into one.
    """

    path: str
    code: str
    line: int

    def as_dict(self) -> dict[str, object]:
        return {"file": self.path, "code": self.code, "line": self.line}


def parse_ruff_json(payload: str, *, root: Path) -> set[LintFinding]:
    """Parse ``ruff check --output-format json`` output into findings.

    ``root`` relativises absolute filenames so baseline and working-tree
    findings are comparable regardless of where each tree lives on disk.
    """
    if not payload.strip():
        return set()
    try:
        records = json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"could not parse ruff JSON output: {exc}") from exc

    findings: set[LintFinding] = set()
    for rec in records:
        raw_name = rec.get("filename") or ""
        rel = _relativise(raw_name, root)
        code = rec.get("code") or "UNKNOWN"
        location = rec.get("location") or {}
        line = int(location.get("row", 0) or 0)
        findings.add(LintFinding(path=rel, code=code, line=line))
    return findings


def reconstruct_nodeid(classname: str, name: str, file: str | None = None) -> str:
    """Rebuild a pytest nodeid from junit ``classname``/``name`` (and ``file``).

    junit collapses the nodeid: a function test ``tests/test_x.py::test_y`` becomes
    ``classname="tests.test_x" name="test_y"``; a class-based test
    ``tests/test_x.py::TestC::test_y`` becomes ``classname="tests.test_x.TestC"``.

    When the ``file`` attribute is present (modern pytest) we locate the module name
    (the file stem) inside the dotted ``classname`` and treat any segments after it as
    class parts. This is robust to the classname carrying a different package prefix
    than the file path (which happens when pytest's rootdir/import mode differs between
    CI and local runs). Otherwise we fall back to the convention that trailing
    Capitalised dotted segments are class names.
    """
    if file:
        file = file.replace("\\", "/")
        module_name = Path(file).stem
        class_parts: list[str] = []
        if classname:
            parts = classname.split(".")
            if module_name in parts:
                class_parts = parts[parts.index(module_name) + 1 :]
            elif parts and parts[-1] != module_name:
                # No module segment at all: keep only trailing Capitalised (class) parts.
                class_parts = [p for p in parts if p[:1].isupper()]
        return "::".join([file, *class_parts, name])

    parts = classname.split(".") if classname else []
    class_parts = []
    while parts and parts[-1][:1].isupper():
        class_parts.insert(0, parts.pop())
    module_path = "/".join(parts) + ".py" if parts else ""
    segments = [seg for seg in [module_path, *class_parts, name] if seg]
    return "::".join(segments)


def parse_junit_failures(payload: str) -> set[str]:
    """Return the set of failed/errored test nodeids from junit XML text."""
    if not payload.strip():
        return set()
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"could not parse junit XML: {exc}") from exc

    failures: set[str] = set()
    for case in root.iter("testcase"):
        broken = any(child.tag in {"failure", "error"} for child in case)
        if not broken:
            continue
        nodeid = reconstruct_nodeid(
            case.get("classname", ""),
            case.get("name", ""),
            case.get("file"),
        )
        failures.add(nodeid)
    return failures


def compute_net_new(baseline: set, current: set) -> list:
    """Return items present in *current* but not in *baseline*, sorted stably."""
    return sorted(current - baseline)


def _relativise(raw: str, root: Path) -> str:
    """Best-effort relativise *raw* against *root*; fall back to the basename."""
    if not raw:
        return ""
    candidate = Path(raw)
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return candidate.name


# ---------------------------------------------------------------------------
# Tooling invocation
# ---------------------------------------------------------------------------


def run_ruff(tree: Path, lint_paths: Sequence[str], *, timeout: int) -> set[LintFinding]:
    """Run ruff in *tree* over *lint_paths* and return findings."""
    cmd = ["ruff", "check", *lint_paths, "--output-format", "json"]
    logger.debug("ruff: %s (cwd=%s)", " ".join(cmd), tree)
    try:
        proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ConfigError("ruff is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConfigError(f"ruff timed out after {timeout}s") from exc
    # ruff exits 0 (clean) or 1 (violations found); anything else (e.g. 2 = config/internal
    # error) must surface, otherwise empty stdout would be parsed as "0 findings" and the
    # gate would pass silently on a broken lint run.
    if proc.returncode not in (0, 1):
        raise ConfigError(f"ruff failed with exit code {proc.returncode}: {proc.stderr.strip()}")
    return parse_ruff_json(proc.stdout, root=tree)


def run_pytest(tree: Path, test_paths: Sequence[str], *, timeout: int) -> set[str]:
    """Run the offline pytest suite in *tree* and return failed nodeids."""
    junit = tree / ".regression_gate_junit.xml"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *test_paths,
        "-p",
        "no:cacheprovider",
        "-q",
        f"--junitxml={junit}",
    ]
    logger.debug("pytest: %s (cwd=%s)", " ".join(cmd), tree)
    try:
        try:
            subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:  # pragma: no cover - defensive
            raise ConfigError("pytest is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ConfigError(f"pytest timed out after {timeout}s") from exc
        if not junit.exists():
            raise ConfigError("pytest did not produce a junit report (collection error?)")
        return parse_junit_failures(junit.read_text(encoding="utf-8"))
    finally:
        # Always remove the temp report, even if parsing raised mid-way.
        junit.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Baseline worktree management
# ---------------------------------------------------------------------------


def _git(args: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def create_baseline_worktree(base_ref: str) -> Path:
    """Materialise *base_ref* in a detached, isolated worktree; return its path."""
    tmp = Path(tempfile.mkdtemp(prefix="regression-baseline-"))
    result = _git(["worktree", "add", "--detach", str(tmp), base_ref])
    if result.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ConfigError(f"git worktree add for ref '{base_ref}' failed: {result.stderr.strip()}")
    logger.info("Baseline worktree for '%s' at %s", base_ref, tmp)
    return tmp


def remove_baseline_worktree(path: Path) -> None:
    """Remove a baseline worktree, tolerating partial state."""
    result = _git(["worktree", "remove", "--force", str(path)])
    if result.returncode != 0:
        logger.warning("git worktree remove failed (%s); pruning", result.stderr.strip())
        _git(["worktree", "prune"])
        shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class GateReport:
    schema_version: str
    base_ref: str
    mode: str
    passed: bool
    net_new_lint: list[dict[str, object]]
    net_new_tests: list[str]
    baseline_lint_count: int
    current_lint_count: int
    baseline_test_failures: int
    current_test_failures: int

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def build_report(
    *,
    base_ref: str,
    mode: str,
    baseline_lint: set[LintFinding],
    current_lint: set[LintFinding],
    baseline_tests: set[str],
    current_tests: set[str],
) -> GateReport:
    """Diff baseline vs current and assemble the structured report."""
    net_lint = compute_net_new(baseline_lint, current_lint)
    net_tests = compute_net_new(baseline_tests, current_tests)
    passed = not net_lint and not net_tests
    return GateReport(
        schema_version=REPORT_SCHEMA_VERSION,
        base_ref=base_ref,
        mode=mode,
        passed=passed,
        net_new_lint=[f.as_dict() for f in net_lint],
        net_new_tests=list(net_tests),
        baseline_lint_count=len(baseline_lint),
        current_lint_count=len(current_lint),
        baseline_test_failures=len(baseline_tests),
        current_test_failures=len(current_tests),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_gate(
    *,
    base_ref: str,
    lint_paths: Sequence[str],
    test_paths: Sequence[str],
    mode: str,
    timeout: int,
) -> GateReport:
    """Run lint + offline tests in working tree and baseline; return the report."""
    cwd = Path.cwd()
    logger.info("Scanning working tree…")
    current_lint = run_ruff(cwd, lint_paths, timeout=timeout)
    current_tests = run_pytest(cwd, test_paths, timeout=timeout)

    baseline = create_baseline_worktree(base_ref)
    try:
        logger.info("Scanning baseline…")
        baseline_lint = run_ruff(baseline, lint_paths, timeout=timeout)
        baseline_tests = run_pytest(baseline, test_paths, timeout=timeout)
    finally:
        remove_baseline_worktree(baseline)

    return build_report(
        base_ref=base_ref,
        mode=mode,
        baseline_lint=baseline_lint,
        current_lint=current_lint,
        baseline_tests=baseline_tests,
        current_tests=current_tests,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-ref", default=DEFAULT_BASE_REF, help=f"Baseline git ref (default: {DEFAULT_BASE_REF})")
    parser.add_argument(
        "--lint-paths",
        nargs="+",
        default=list(DEFAULT_LINT_PATHS),
        help="Paths passed to ruff (default mirrors CI: src tests)",
    )
    parser.add_argument(
        "--test-paths",
        nargs="+",
        default=list(DEFAULT_TEST_PATHS),
        help="Offline test paths passed to pytest (default: tests)",
    )
    parser.add_argument(
        "--mode",
        choices=GateMode.ALL,
        default=GateMode.BLOCK,
        help="block: net-new findings exit 1; warn: report only (default: block)",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-command timeout in seconds")
    parser.add_argument("--report-path", default=DEFAULT_REPORT_PATH, help="Where to write the JSON report")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    try:
        report = run_gate(
            base_ref=args.base_ref,
            lint_paths=args.lint_paths,
            test_paths=args.test_paths,
            mode=args.mode,
            timeout=args.timeout,
        )
    except ConfigError as exc:
        print(f"regression-gate: configuration error: {exc}")
        return 2

    Path(args.report_path).write_text(report.to_json(), encoding="utf-8")
    logger.info("Report written to %s", args.report_path)

    if report.passed:
        print("regression-gate: OK — no net-new lint/test findings vs", args.base_ref)
        return 0

    print("regression-gate: NET-NEW findings vs", args.base_ref)
    for item in report.net_new_lint:
        print(f"  - lint {item['file']}:{item['line']} {item['code']}")
    for nodeid in report.net_new_tests:
        print(f"  - test {nodeid}")

    if args.mode == GateMode.WARN:
        print("regression-gate: mode=warn — not failing the build.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
