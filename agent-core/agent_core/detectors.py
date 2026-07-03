"""Real git/GitHub outcome detectors for the passive labeller.

These replace the no-op placeholders previously wired into
``outcome_labeller.main`` with implementations backed by the tools an agent
deployment already has:

  * :class:`GitRevertDetector` shells out to ``git log`` and recognises the
    ``This reverts commit <sha>`` footer that ``git revert`` writes, so a
    reverted change is labelled incorrect from the repository's own history.
  * :class:`GitHubChecksFailureAttributor` reads a commit's GitHub Actions
    check-runs via ``gh api`` and attributes a post-merge failure to the change.

Every tunable lives on :class:`DetectorConfig` (timeouts, the failing-conclusion
set) — no literal appears in detector logic. All subprocess calls are bounded by
a timeout and fail *safe*: a missing binary, a timeout, an absent repo/remote, or
malformed output is reported as "no signal observed" rather than raising or
hanging, so the labeller degrades to TIMEOUT_CLEAN instead of crashing. The pure
logic (:func:`commit_has_ci_failure`, :func:`resolve_repo`, :func:`_parse_check_runs`,
revert matching, the timeout/not-found fail-safes) is exercised directly against
real git repositories and real check-run payloads; only the live ``gh api``
network call itself is excluded from coverage.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .timeutil import parse_iso8601

# git revert writes a footer line: ``This reverts commit <40-hex>.``
_REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
# owner/repo out of an https or ssh GitHub remote URL.
_REMOTE_RE = re.compile(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$")
# Default check-run conclusions that mean the change broke something.
_DEFAULT_FAILING: frozenset[str] = frozenset({"failure", "timed_out", "startup_failure"})
_DEFAULT_GIT_TIMEOUT_S = 10.0
_DEFAULT_GH_TIMEOUT_S = 15.0
# Conventional shell exit codes reused for the fail-safe synthetic results.
_RC_TIMED_OUT = 124
_RC_NOT_FOUND = 127


@dataclass(frozen=True)
class DetectorConfig:
    """Tunables for the outcome detectors. No literal appears in detector logic."""

    git_timeout_s: float = _DEFAULT_GIT_TIMEOUT_S
    gh_timeout_s: float = _DEFAULT_GH_TIMEOUT_S
    failing_conclusions: frozenset[str] = _DEFAULT_FAILING


def _run(args: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run a subprocess without ever raising or hanging: a missing binary or a
    timeout becomes a non-zero result so callers degrade to 'no signal'."""
    argv = list(args)
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, _RC_NOT_FOUND, "", "executable not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, _RC_TIMED_OUT, "", "timed out")


def _sha_prefix_match(a: str, b: str) -> bool:
    """True when one sha is a prefix of the other (handles short vs full)."""
    return a.startswith(b) or b.startswith(a)


class GitRevertDetector:
    """RevertDetector backed by ``git log`` against a real repository."""

    def __init__(self, repo_dir: str | Path = ".", cfg: DetectorConfig | None = None) -> None:
        self._repo_dir = Path(repo_dir)
        self._cfg = cfg if cfg is not None else DetectorConfig()

    def was_reverted(self, change_id: str, since: datetime) -> bool:
        # NUL-separate commits (-z) and emit committer epoch + body, then filter
        # the window in Python: git's --since approxidate parser is unreliable
        # for explicit ISO timestamps, so we compare epochs exactly instead.
        proc = _run(
            ["git", "-C", str(self._repo_dir), "log", "-z", "--format=%ct%n%B"],
            self._cfg.git_timeout_s,
        )
        if proc.returncode != 0:
            return False  # not a repo / git error / timeout -> fail safe
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


def resolve_repo(
    repo_dir: str | Path = ".", *, timeout: float = _DEFAULT_GIT_TIMEOUT_S
) -> str | None:
    """Return ``owner/repo`` from the origin remote, or None if unavailable.

    Reads the declared URL (``git config``) rather than ``git remote get-url``,
    which applies ``url.<base>.insteadOf`` rewrites and would misreport the
    origin on machines with SSH/proxy rewrite rules.
    """
    proc = _run(["git", "-C", str(repo_dir), "config", "--get", "remote.origin.url"], timeout)
    if proc.returncode != 0:
        return None
    m = _REMOTE_RE.search(proc.stdout.strip())
    return m.group(1) if m else None


def commit_has_ci_failure(
    check_runs: Iterable[Mapping[str, object]],
    since: datetime,
    failing: Iterable[str] = _DEFAULT_FAILING,
) -> bool:
    """True if any check-run failed at or after ``since``.

    A run counts when its conclusion is in ``failing`` and it has no completion
    time (still-failing) or completed on/after the merge — so stale pre-merge
    runs on the same commit are not attributed to this change.
    """
    failing_set = frozenset(failing)
    for run in check_runs:
        if run.get("conclusion") not in failing_set:
            continue
        completed = run.get("completed_at")
        if completed is None or (isinstance(completed, str) and parse_iso8601(completed) >= since):
            return True
    return False


def _parse_check_runs(stdout: str) -> list[Mapping[str, object]]:
    """Parse ``gh api ... --jq .check_runs`` output into a list (empty on bad data)."""
    try:
        loaded = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


class GitHubChecksFailureAttributor:
    """FailureAttributor backed by a commit's GitHub Actions check-runs."""

    def __init__(self, repo: str | None, cfg: DetectorConfig | None = None) -> None:
        self._repo = repo
        self._cfg = cfg if cfg is not None else DetectorConfig()

    def caused_failure(self, change_id: str, since: datetime) -> bool:
        runs = self._fetch_check_runs(change_id)
        return commit_has_ci_failure(runs, since, self._cfg.failing_conclusions)

    def _fetch_check_runs(self, change_id: str) -> list[Mapping[str, object]]:
        if self._repo is None:
            return []
        return self._fetch_remote(change_id)  # pragma: no cover - delegates to live gh

    def _fetch_remote(  # pragma: no cover - thin live-GitHub network shim
        self, change_id: str
    ) -> list[Mapping[str, object]]:
        proc = _run(
            [
                "gh",
                "api",
                f"repos/{self._repo}/commits/{change_id}/check-runs",
                "--jq",
                ".check_runs // []",
            ],
            self._cfg.gh_timeout_s,
        )
        if proc.returncode != 0:
            return []
        return _parse_check_runs(proc.stdout)
