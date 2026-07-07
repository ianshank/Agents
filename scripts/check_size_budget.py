#!/usr/bin/env python3
"""CI guard: enforce the project's size budgets on source files.

The project documents four structural limits. Two are enforced elsewhere by ruff
(cyclomatic complexity < 15 via ``C901``; line length via the formatter). The two
this guard owns:

  * **File length** — no source ``*.py`` file exceeds :data:`MAX_FILE_LINES` lines.
    This is a HARD gate: exceeding it fails CI (exit 1).
  * **Function length** (> :data:`MAX_FUNCTION_LINES` physical lines) and
    **public methods per class** (> :data:`MAX_PUBLIC_METHODS`) are reported as
    NON-BLOCKING warnings. The codebase carries a documented backlog of functions
    over the line budget (many are argparse ``main()`` bodies and validation gates),
    so these are surfaced for visibility without gating — see
    ``docs/decisions/0019-size-budget-gate.md``. Silent truncation is avoided: every
    over-budget item is listed.

  python scripts/check_size_budget.py            # human-readable report
  python scripts/check_size_budget.py --json     # machine-readable report
  python scripts/check_size_budget.py --root src --root agent-core   # limit scope

Exit codes:
    0 - no file exceeds the hard file-length budget (warnings may still be printed)
    1 - at least one file exceeds the hard file-length budget
    2 - configuration / usage error
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from _cli import configure_logging

logger = logging.getLogger(__name__)

# Structural budgets (single source of truth; no magic numbers at call sites).
MAX_FILE_LINES = 500
MAX_FUNCTION_LINES = 50
MAX_PUBLIC_METHODS = 15

# Directory names never scanned: test suites (legitimately long), caches, build output,
# VCS, and synthetic fixtures whose shape is deliberate. The common virtualenv names are a
# cheap fast-path; env directories under *any* name are additionally caught by their
# ``pyvenv.cfg`` marker (see :func:`_is_virtualenv_dir`), so ``.venv-ci`` / ``env311`` /
# ``py312`` are skipped too — no reliance on a hardcoded name matching the developer's env.
EXCLUDED_DIR_NAMES = frozenset(
    {
        "tests",
        "__pycache__",
        ".git",
        ".grimp_cache",
        "build",
        "dist",
        "node_modules",
        "fixtures",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        ".eggs",
    }
)

# Canonical marker of a PEP 405 virtualenv: a ``pyvenv.cfg`` at the environment root.
VENV_MARKER = "pyvenv.cfg"

# Exit code for a configuration / usage error (matches the module docstring contract).
EXIT_USAGE_ERROR = 2


@dataclass(frozen=True)
class Finding:
    """One budget observation. ``hard`` findings gate CI; others are warnings."""

    kind: str  # "file_lines" | "function_lines" | "public_methods"
    path: str
    name: str  # symbol name, or "" for a whole-file finding
    value: int
    limit: int
    hard: bool


def _repo_root() -> Path:
    """Repo root (parent of the ``scripts/`` directory holding this file)."""
    return Path(__file__).resolve().parent.parent


def _is_excluded(path: Path, root: Path) -> bool:
    """True when any path segment below *root* is an excluded directory name.

    A path outside *root* has no segments below it to exclude, so it is simply not
    excluded — this keeps a ``--root`` pointed outside the repo from raising ``ValueError``.
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return any(part in EXCLUDED_DIR_NAMES for part in relative.parts)


def _is_virtualenv_dir(directory: Path) -> bool:
    """True when *directory* is the root of a PEP 405 virtualenv.

    Detects the environment by its canonical ``pyvenv.cfg`` marker instead of a hardcoded
    set of names, so a developer's local env — whatever it is called (``.venv-ci``,
    ``env``, ``py312``) — is skipped and never raises spurious findings against the
    third-party code vendored inside it.
    """
    return (directory / VENV_MARKER).is_file()


def iter_source_files(roots: Iterable[Path], repo_root: Path) -> list[Path]:
    """All non-excluded ``*.py`` files under *roots*, sorted for deterministic output.

    A root may be a directory (walked recursively) or an individual ``*.py`` file, so the
    gate also works when invoked on a single file (e.g. from a pre-commit hook). Excluded
    directories (see :data:`EXCLUDED_DIR_NAMES`) and virtualenvs (see
    :func:`_is_virtualenv_dir`) are pruned during the walk, so the scan never descends into
    them — cheaper than descending-then-filtering, and robust to any virtualenv name.
    """
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root.suffix == ".py" and not _is_excluded(root, repo_root):
                seen.add(root)
            continue
        if _is_virtualenv_dir(root):  # a root pointed directly at an env: skip wholesale
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            # Prune in place so os.walk never descends into excluded dirs or virtualenvs.
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES and not _is_virtualenv_dir(here / d)]
            for filename in filenames:
                if filename.endswith(".py"):
                    seen.add(here / filename)
    return sorted(seen)


def _public_method_count(node: ast.ClassDef) -> int:
    """Number of distinct public (non-underscore) method names directly on *node*.

    Deduplicated by name so ``@overload`` stubs and property getter/setter/deleter trios
    (each a separate ``FunctionDef`` with the same name) count once, not several times.
    """
    methods = (child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return len({m.name for m in methods if not m.name.startswith("_")})


def _node_line_span(node: ast.stmt) -> int:
    """Physical line count of a statement node (functions/classes carry positions)."""
    end = node.end_lineno if node.end_lineno is not None else node.lineno
    return end - node.lineno + 1


def scan_file(path: Path, repo_root: Path) -> list[Finding]:
    """Collect every budget finding for a single source file."""
    rel = str(path.relative_to(repo_root))
    # A CI gate must survive a non-UTF-8 byte in some vendored/source file: decode with
    # errors="replace" so an undecodable file is still line-counted and (best-effort)
    # parsed instead of aborting the whole scan (mirrors the SyntaxError resilience below).
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[Finding] = []

    line_count = len(text.splitlines())
    if line_count > MAX_FILE_LINES:
        findings.append(Finding("file_lines", rel, "", line_count, MAX_FILE_LINES, hard=True))

    try:
        tree = ast.parse(text)
    except SyntaxError:
        logger.warning("could not parse %s; skipping symbol-level checks", rel)
        return findings

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = _node_line_span(node)
            if span > MAX_FUNCTION_LINES:
                findings.append(Finding("function_lines", rel, node.name, span, MAX_FUNCTION_LINES, hard=False))
        elif isinstance(node, ast.ClassDef):
            count = _public_method_count(node)
            if count > MAX_PUBLIC_METHODS:
                findings.append(Finding("public_methods", rel, node.name, count, MAX_PUBLIC_METHODS, hard=False))
    return findings


def scan(roots: Sequence[Path] | None = None, *, repo_root: Path | None = None) -> list[Finding]:
    """Scan *roots* (default: the whole repo) and return all findings, sorted.

    Roots and the repo root are resolved to absolute paths so a relative ``--root``
    (e.g. ``agent-core``) does not break the ``relative_to`` exclusion check.
    """
    base = (repo_root if repo_root is not None else _repo_root()).resolve()
    scan_roots = [r.resolve() for r in roots] if roots else [base]
    # Confine scanning to the repo: an out-of-repo root is a usage error (main() maps a
    # ValueError to exit 2), caught here early so even a root with no *.py files is reported.
    for root in scan_roots:
        if root != base and base not in root.parents:
            raise ValueError(f"root {root} is outside the repository root {base}")
    findings: list[Finding] = []
    for path in iter_source_files(scan_roots, base):
        findings.extend(scan_file(path, base))
    return sorted(findings, key=lambda f: (not f.hard, f.kind, f.path, f.name))


def _report(findings: list[Finding]) -> None:
    """Print a human-readable summary of findings."""
    hard = [f for f in findings if f.hard]
    warnings = [f for f in findings if not f.hard]
    for f in warnings:
        print(f"[warn] {f.kind}: {f.path}::{f.name or '<file>'} = {f.value} (> {f.limit})")
    if hard:
        print(f"size-budget: FAIL - {len(hard)} file(s) over {MAX_FILE_LINES} lines:")
        for f in hard:
            print(f"  {f.path}: {f.value} lines (> {f.limit})")
    else:
        print(f"size-budget: OK - no file exceeds {MAX_FILE_LINES} lines ({len(warnings)} warning(s)).")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Enforce source-file size budgets.")
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        default=None,
        help="Directory to scan (repeatable); defaults to the whole repo.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON report on stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the size-budget check and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    base = _repo_root()
    roots = [Path(r) for r in args.roots] if args.roots else None
    try:
        findings = scan(roots, repo_root=base)
    except (ValueError, OSError) as exc:
        # A --root outside the repo (or an unreadable path) is a usage error, not a crash:
        # honour the documented exit-2 contract with a readable message.
        logger.error("cannot scan requested roots: %s", exc)
        print(f"size-budget: usage error — {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    hard_failures = [f for f in findings if f.hard]

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2, sort_keys=True))
    else:
        _report(findings)

    return 1 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
