"""Real git/GitHub outcome detectors for the passive labeller.

These replace the no-op placeholders previously wired into
``outcome_labeller.main`` with implementations backed by the tools an agent
deployment already has:

  * :class:`GitRevertDetector` shells out to ``git log`` and recognises the
    ``This reverts commit <sha>`` footer that ``git revert`` writes, so a
    reverted change is labelled incorrect from the repository's own history.
  * :class:`GitHubChecksFailureAttributor` reads a commit's GitHub Actions
    check-runs via ``gh api`` and attributes a post-merge failure to the change.

Both fail *safe*: when the repo/remote is unavailable (or the binary is
missing) they report "no signal observed" rather than raising, so the labeller
degrades to TIMEOUT_CLEAN instead of crashing. The pure decision logic
(:func:`commit_has_ci_failure`, :func:`resolve_repo`, revert matching) is
exercised directly against real git repositories and real check-run payloads;
only the live ``gh api`` network call is excluded from coverage.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

# git revert writes a footer line: ``This reverts commit <40-hex>.``
_REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
# owner/repo out of an https or ssh GitHub remote URL.
_REMOTE_RE = re.compile(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$")
# check-run conclusions that mean the change broke something.
_FAILING = frozenset({"failure", "timed_out", "startup_failure"})


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(args), capture_output=True, text=True)
    except FileNotFoundError:  # pragma: no cover - git/gh not installed
        return subprocess.CompletedProcess(list(args), 127, "", "executable not found")


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z' (rejected by
    datetime.fromisoformat before Python 3.11)."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _sha_prefix_match(a: str, b: str) -> bool:
    """True when one sha is a prefix of the other (handles short vs full)."""
    return a.startswith(b) or b.startswith(a)


class GitRevertDetector:
    """RevertDetector backed by ``git log`` against a real repository."""

    def __init__(self, repo_dir: str | Path = ".") -> None:
        self._repo_dir = Path(repo_dir)

    def was_reverted(self, change_id: str, since: datetime) -> bool:
        # NUL-separate commits (-z) and emit committer epoch + body, then filter
        # the window in Python: git's --since approxidate parser is unreliable
        # for explicit ISO timestamps, so we compare epochs exactly instead.
        proc = _run(["git", "-C", str(self._repo_dir), "log", "-z", "--format=%ct%n%B"])
        if proc.returncode != 0:
            return False  # not a repo / git error -> fail safe
        cutoff = since.timestamp()
        for entry in proc.stdout.split("\x00"):
            if not entry.strip():
                continue
            ts_str, _, body = entry.partition("\n")
            if int(ts_str.strip()) < cutoff:
                continue  # committed before the change merged -> not its revert
            m = _REVERT_RE.search(body)
            if m and _sha_prefix_match(m.group(1), change_id):
                return True
        return False


def resolve_repo(repo_dir: str | Path = ".") -> str | None:
    """Return ``owner/repo`` from the origin remote, or None if unavailable."""
    proc = _run(["git", "-C", str(repo_dir), "remote", "get-url", "origin"])
    if proc.returncode != 0:
        return None
    m = _REMOTE_RE.search(proc.stdout.strip())
    return m.group(1) if m else None


def commit_has_ci_failure(check_runs: Iterable[Mapping[str, object]], since: datetime) -> bool:
    """True if any check-run failed at or after ``since``.

    A run counts when its conclusion is failing and it has no completion time
    (still-failing) or completed on/after the merge — so stale pre-merge runs
    on the same commit are not attributed to this change.
    """
    for run in check_runs:
        if run.get("conclusion") not in _FAILING:
            continue
        completed = run.get("completed_at")
        if completed is None or (isinstance(completed, str) and _parse_ts(completed) >= since):
            return True
    return False


class GitHubChecksFailureAttributor:
    """FailureAttributor backed by a commit's GitHub Actions check-runs."""

    def __init__(self, repo: str | None) -> None:
        self._repo = repo

    def caused_failure(self, change_id: str, since: datetime) -> bool:
        return commit_has_ci_failure(self._fetch_check_runs(change_id), since)

    def _fetch_check_runs(  # pragma: no cover - thin live-GitHub network shim
        self, change_id: str
    ) -> list[Mapping[str, object]]:
        if self._repo is None:
            return []
        proc = _run(
            [
                "gh",
                "api",
                f"repos/{self._repo}/commits/{change_id}/check-runs",
                "--jq",
                ".check_runs // []",
            ]
        )
        if proc.returncode != 0:
            return []
        try:
            loaded = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return []
        return loaded if isinstance(loaded, list) else []
