"""Tests for the real git/GitHub outcome detectors.

No mocks: revert detection runs against REAL temporary git repositories, and
the CI-failure logic is exercised against REAL GitHub check-run payload shapes.
The only code not covered here is the thin live-`gh` network shim (pragma'd),
which cannot be exercised deterministically offline without a mock.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from agent_core.detectors import (
    DetectorConfig,
    GitHubChecksFailureAttributor,
    GitRevertDetector,
    _parse_check_runs,
    _run,
    commit_has_ci_failure,
    resolve_repo,
)
from agent_core.outcome_labeller import main
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore

SINCE = datetime(2000, 1, 1, tzinfo=timezone.utc)


# Real-git helpers shared with test_store_sync (tests/gitrepo.py).
from gitrepo import commit as _commit  # noqa: E402
from gitrepo import git as _git  # noqa: E402
from gitrepo import init_repo as _init_repo  # noqa: E402


# --- GitRevertDetector (real git) -------------------------------------------
def test_revert_detected_when_commit_reverted(tmp_path):
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    _commit(repo, "b.txt", "v1", "add b")
    _git(repo, "revert", "--no-edit", sha)  # writes "This reverts commit <sha>."
    assert GitRevertDetector(repo).was_reverted(sha, SINCE) is True


def test_not_reverted_returns_false(tmp_path):
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    assert GitRevertDetector(repo).was_reverted(sha, SINCE) is False


def test_revert_matches_short_sha(tmp_path):
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    _git(repo, "revert", "--no-edit", sha)
    assert GitRevertDetector(repo).was_reverted(sha[:8], SINCE) is True


def test_revert_outside_window_is_ignored(tmp_path):
    # `since` in the far future: the revert (committed now) predates it, so the
    # --since window excludes it -> not counted.
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    _git(repo, "revert", "--no-edit", sha)
    future = datetime(2999, 1, 1, tzinfo=timezone.utc)
    assert GitRevertDetector(repo).was_reverted(sha, future) is False


def test_revert_detector_off_repo_fails_safe(tmp_path):
    # Not a git repo -> git errors -> "no revert observed" (fail safe).
    assert GitRevertDetector(tmp_path / "nope").was_reverted("deadbeef", SINCE) is False


# --- resolve_repo (real git remote) -----------------------------------------
def test_resolve_repo_from_https_remote(tmp_path):
    repo = _init_repo(tmp_path / "r")
    _git(repo, "remote", "add", "origin", "https://github.com/ianshank/Agents.git")
    assert resolve_repo(repo) == "ianshank/Agents"


def test_resolve_repo_from_ssh_remote(tmp_path):
    repo = _init_repo(tmp_path / "r")
    _git(repo, "remote", "add", "origin", "git@github.com:ianshank/Agents.git")
    assert resolve_repo(repo) == "ianshank/Agents"


def test_resolve_repo_none_without_remote(tmp_path):
    repo = _init_repo(tmp_path / "r")
    assert resolve_repo(repo) is None


def test_resolve_repo_none_off_repo(tmp_path):
    assert resolve_repo(tmp_path / "nope") is None


# --- commit_has_ci_failure (real check-run payload shapes) -------------------
def test_ci_failure_true_on_failed_run():
    runs = [
        {"conclusion": "success", "completed_at": "2026-01-02T00:00:00Z"},
        {"conclusion": "failure", "completed_at": "2026-01-02T00:00:00Z"},
    ]
    assert commit_has_ci_failure(runs, SINCE) is True


def test_ci_failure_false_when_all_pass():
    runs = [{"conclusion": "success", "completed_at": "2026-01-02T00:00:00Z"}]
    assert commit_has_ci_failure(runs, SINCE) is False


def test_ci_failure_counts_timed_out_and_startup_failure():
    assert commit_has_ci_failure([{"conclusion": "timed_out", "completed_at": None}], SINCE) is True
    assert (
        commit_has_ci_failure([{"conclusion": "startup_failure", "completed_at": None}], SINCE)
        is True
    )


def test_ci_failure_ignores_failures_before_since():
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    runs = [{"conclusion": "failure", "completed_at": "2026-01-01T00:00:00Z"}]  # pre-merge
    assert commit_has_ci_failure(runs, since) is False


def test_ci_failure_empty_is_false():
    assert commit_has_ci_failure([], SINCE) is False


def test_ci_failure_parses_offset_timestamp():
    # completed_at without a 'Z' (explicit offset form) must also parse.
    runs = [{"conclusion": "failure", "completed_at": "2026-01-02T00:00:00+00:00"}]
    assert commit_has_ci_failure(runs, SINCE) is True


def test_ci_failure_respects_custom_failing_set():
    # 'cancelled' is not failing by default, but a custom set can opt it in.
    runs = [{"conclusion": "cancelled", "completed_at": None}]
    assert commit_has_ci_failure(runs, SINCE) is False
    assert commit_has_ci_failure(runs, SINCE, failing={"cancelled"}) is True


# --- _run hardening: real subprocesses, never hangs or raises ----------------
def test_run_times_out_returns_124():
    # A real child that outlives the timeout fails safe (rc 124), never hangs.
    proc = _run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    assert proc.returncode == 124


def test_run_missing_binary_returns_127():
    proc = _run(["agent-core-nonexistent-binary-xyz"], timeout=5)
    assert proc.returncode == 127


# --- _parse_check_runs: real `gh` output shapes ------------------------------
def test_parse_check_runs_valid_list():
    assert _parse_check_runs('[{"conclusion": "failure"}]') == [{"conclusion": "failure"}]


def test_parse_check_runs_empty_string_is_empty():
    assert _parse_check_runs("") == []


def test_parse_check_runs_invalid_json_is_empty():
    assert _parse_check_runs("not json") == []


def test_parse_check_runs_non_list_is_empty():
    assert _parse_check_runs('{"check_runs": 1}') == []


# --- DetectorConfig is threaded through both detectors -----------------------
def test_detectors_accept_explicit_config(tmp_path):
    cfg = DetectorConfig(
        git_timeout_s=5.0, gh_timeout_s=5.0, failing_conclusions=frozenset({"cancelled"})
    )
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    _git(repo, "revert", "--no-edit", sha)
    assert GitRevertDetector(repo, cfg).was_reverted(sha, SINCE) is True
    # custom failing set + no repo -> still fails safe to False (no network)
    assert GitHubChecksFailureAttributor(None, cfg).caused_failure(sha, SINCE) is False


# --- GitHubChecksFailureAttributor fail-safe --------------------------------
def test_github_attributor_no_repo_fails_safe():
    # No repo configured -> never touches the network -> "no failure observed".
    assert GitHubChecksFailureAttributor(repo=None).caused_failure("c1", SINCE) is False


# --- end-to-end: main() labels a real git revert ----------------------------
def test_main_labels_real_revert_incorrect(tmp_path):
    # Drive outcome_labeller.main() against a REAL repo where the change's commit
    # was reverted: the labeller must mark it incorrect (REVERT). No mocks.
    repo = _init_repo(tmp_path / "repo")
    sha = _commit(repo, "f.txt", "v1", "add f")
    _git(repo, "revert", "--no-edit", sha)
    store = OutcomeStore(tmp_path / "s.jsonl")
    store.append(
        OutcomeRecord(
            change_id=sha, domain="core", raw_confidence=0.9, merged_at="2000-01-01T00:00:00+00:00"
        )
    )
    rc = main(["--store", str(store.path), "--repo-dir", str(repo)])
    assert rc == 0
    resolved = store.resolved()[sha]
    assert resolved.label is False and resolved.label_source == LabelSource.REVERT.value


# --- degrade paths emit WARNING logs (fail-safe is observable, never silent) --
def test_run_missing_binary_warns(caplog):
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        _run(["agent-core-nonexistent-binary-xyz"], timeout=5)
    assert any("executable not found" in r.message for r in caplog.records)


def test_run_timeout_warns(caplog):
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        _run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
    assert any("timed out" in r.message for r in caplog.records)


def test_parse_check_runs_invalid_json_warns(caplog):
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        _parse_check_runs("not json")
    assert any("unparseable check-runs payload" in r.message for r in caplog.records)


def test_parse_check_runs_non_list_warns(caplog):
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        _parse_check_runs('{"check_runs": 1}')
    assert any("unexpected check-runs payload type" in r.message for r in caplog.records)


def test_resolve_repo_without_remote_warns(tmp_path, caplog):
    repo = _init_repo(tmp_path / "r")  # real repo, but no origin remote configured
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        assert resolve_repo(repo) is None
    assert any("origin remote unreadable" in r.message for r in caplog.records)


def test_resolve_repo_non_github_remote_warns(tmp_path, caplog):
    repo = _init_repo(tmp_path / "r")
    _git(repo, "remote", "add", "origin", "https://gitlab.example.com/o/r.git")
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        assert resolve_repo(repo) is None
    assert any("not a GitHub URL" in r.message for r in caplog.records)


def test_revert_detector_off_repo_warns(tmp_path, caplog):
    with caplog.at_level("WARNING", logger="agent_core.detectors"):
        assert GitRevertDetector(tmp_path / "not-a-repo").was_reverted("abc123", SINCE) is False
    assert any("revert signal unavailable" in r.message for r in caplog.records)


def test_revert_detected_logs_info(tmp_path, caplog):
    repo = _init_repo(tmp_path / "r")
    sha = _commit(repo, "a.txt", "v1", "add a")
    _git(repo, "revert", "--no-edit", sha)
    with caplog.at_level("INFO", logger="agent_core.detectors"):
        assert GitRevertDetector(repo).was_reverted(sha, SINCE) is True
    assert any("revert detected" in r.message for r in caplog.records)
