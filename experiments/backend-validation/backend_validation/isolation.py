"""Subtree-isolation check: the experiment must not change anything outside its allowlist.

This is the PR-scoped half of the isolation story (spec R7): it compares the working tree
against a base ref and fails on any changed or untracked path outside the allowlist. It is
run at pre-push time and in the runbook — deliberately NOT inside the permanent quality
gate, where it would false-flag unrelated branches after this experiment merges. The
permanent half lives in settings (output paths must resolve under the subtree) and in the
compose bind-mount test.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend_validation.logging_util import get_logger
from backend_validation.procrun import CommandRunner

logger = get_logger(__name__)


class IsolationError(RuntimeError):
    """Raised when git itself cannot answer (not when a violation is found)."""


@dataclass(frozen=True)
class IsolationResult:
    ok: bool
    violations: tuple[str, ...] = ()
    checked_paths: int = 0


def _diff_paths(runner: CommandRunner, repo_root: Path, base_ref: str) -> list[str]:
    diff = runner.run(["git", "diff", "--name-only", f"{base_ref}...HEAD"], cwd=repo_root)
    if not diff.ok:
        raise IsolationError(f"git diff against {base_ref} failed: {diff.stderr.strip()}")
    return [line.strip() for line in diff.stdout.splitlines() if line.strip()]


def _worktree_paths(runner: CommandRunner, repo_root: Path) -> list[str]:
    status = runner.run(["git", "status", "--porcelain"], cwd=repo_root)
    if not status.ok:
        raise IsolationError(f"git status failed: {status.stderr.strip()}")
    paths: list[str] = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        # Renames render as "old -> new"; the new location is what must stay in-tree.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip('"'))
    return paths


def check_isolation(
    *,
    repo_root: Path,
    base_ref: str,
    allowlist: tuple[str, ...],
    runner: CommandRunner,
) -> IsolationResult:
    """Return violations = changed/untracked paths not under any allowlist prefix.

    ``allowlist`` entries are repo-relative; an entry ending in ``/`` is a prefix, anything
    else must match exactly (e.g. ``CHANGELOG.md``).
    """
    candidates = sorted(set(_diff_paths(runner, repo_root, base_ref)) | set(_worktree_paths(runner, repo_root)))
    violations: list[str] = []
    for path in candidates:
        allowed = any(path.startswith(entry) if entry.endswith("/") else path == entry for entry in allowlist)
        if not allowed:
            violations.append(path)
    result = IsolationResult(ok=not violations, violations=tuple(violations), checked_paths=len(candidates))
    logger.debug("isolation: checked=%d violations=%d", result.checked_paths, len(result.violations))
    return result
