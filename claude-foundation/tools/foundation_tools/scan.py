"""No-hardcode scanner.

Policy (plan §2.1):
  * full Claude model IDs are banned everywhere (aliases belong in frontmatter
    ``model:`` fields only — enforced by the schema validator, not here);
  * absolute filesystem paths are banned in scripts/configs — use
    ``${CLAUDE_PLUGIN_ROOT}`` / ``${CLAUDE_PROJECT_DIR}`` / env vars;
  * credential-shaped literals are banned everywhere.

Scope: component sources (skills/, agents/, hooks/, tools/, .claude-plugin/,
.mcp.json*). Markdown prose in docs/ is exempt by default; extra exclusions
come from ``CLAUDE_FOUNDATION_SCAN_EXCLUDE`` (comma-separated glob patterns).

Usage: ``python -m foundation_tools.scan [--root PATH]``
Exit codes: 0 clean; 1 findings; 2 usage error.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from foundation_tools.jsonlog import get_logger

logger = get_logger("foundation.scan")

SCAN_EXCLUDE_ENV = "CLAUDE_FOUNDATION_SCAN_EXCLUDE"

_SCAN_DIRS = ("skills", "agents", "hooks", "tools", ".claude-plugin")
_SCAN_SUFFIXES = {".py", ".sh", ".json", ".md", ".yaml", ".yml", ".toml"}
_DEFAULT_EXCLUDES = ("docs/*", "tests/*", "*.example")

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("full-model-id", re.compile(r"claude-[a-z0-9]+-[0-9][\w.-]*", re.IGNORECASE)),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("api-key-literal", re.compile(r"(sk|pk)-[A-Za-z0-9_-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    (
        # Assigned secret literals — quoted or bare — excluding env indirection
        # (values beginning with $, <, {) which are placeholders, not secrets.
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:api_?key|secret(?:_key)?|access_key|private_key|token|passwd|password)\b"
            r"\s*[:=]\s*[\"']?[^\s\"'$<{][^\s\"']{5,}"
        ),
    ),
    # Absolute POSIX paths outside portable env indirection; anchored to path-like
    # roots that never belong in portable components.
    (
        "absolute-path",
        re.compile(
            r"(?:^|[\s\"'=(:,>])"
            r"(/(?:home|Users|root|usr|opt|var|tmp|etc|mnt|srv|Applications)/[\w./-]+)"
        ),
    ),
)


def _excluded(rel: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def iter_scan_files(root: Path, extra_excludes: Iterable[str] = ()) -> Iterable[Path]:
    """Yield files in scope, honoring default and configured exclusions."""
    patterns = list(_DEFAULT_EXCLUDES) + list(extra_excludes)
    for base in _SCAN_DIRS:
        base_dir = root / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*")):
            if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            if not _excluded(rel, patterns):
                yield path
    for mcp in sorted(root.glob(".mcp.json*")):
        rel = mcp.relative_to(root).as_posix()
        if not _excluded(rel, patterns):
            yield mcp


def scan_file(path: Path, root: Path) -> list[str]:
    """Return ``rel:line rule 'excerpt'`` findings for one file.

    A ``scan:allow`` marker waives the line, but every waiver is logged (never
    silent) so waived lines stay auditable.
    """
    findings: list[str] = []
    rel = path.relative_to(root).as_posix()
    for lineno, line in enumerate(path.read_text("utf-8", errors="replace").splitlines(), 1):
        hits = [rule for rule, pattern in _RULES if pattern.search(line)]
        if not hits:
            continue
        if "scan:allow" in line:  # explicit, visible-in-diff, LOGGED waiver
            logger.warning("waiver", extra={"location": f"{rel}:{lineno}", "rules": hits})
            continue
        for rule, pattern in _RULES:
            match = pattern.search(line)
            if match:
                findings.append(f"{rel}:{lineno} {rule} {match.group(0)[:60]!r}")
    return findings


def scan_tree(root: Path) -> list[str]:
    """Scan every in-scope file; returns the combined finding list."""
    extra = [p.strip() for p in os.environ.get(SCAN_EXCLUDE_ENV, "").split(",") if p.strip()]
    findings: list[str] = []
    count = 0
    for path in iter_scan_files(root, extra):
        count += 1
        findings.extend(scan_file(path, root))
    logger.info("scan complete", extra={"files": count, "findings": len(findings)})
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="plugin root (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    findings = scan_tree(root)
    if findings:
        print("HARDCODE SCAN FAILED:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("foundation-scan: OK — no hardcoded values found")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
