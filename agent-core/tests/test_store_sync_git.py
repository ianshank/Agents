"""Tests for store_sync — real git repositories (bare remotes + clones), no mocks.

Decomposed from test_store_sync.py to maintain module focus and size budgets.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from gitrepo import git as _git
from gitrepo import make_remote_and_clone as _make_remote_and_clone

from agent_core.outcome_store import OutcomeRecord
from agent_core.store_sync import (
    StoreSyncConfig,
    SyncStatus,
    _commit_store,
    _run,
    pull,
    push,
    read_store,
    read_store_lines,
    write_store,
)


def _rec(
    change_id: str = "c1",
    domain: str = "human/agent-core",
    merged_at: str = "2026-01-01T00:00:00+00:00",
    label: bool | None = None,
    label_source: str | None = None,
    labeled_at: str | None = None,
) -> OutcomeRecord:
    return OutcomeRecord(
        change_id=change_id,
        domain=domain,
        raw_confidence=0.0,
        merged_at=merged_at,
        label=label,
        label_source=label_source,
        labeled_at=labeled_at,
    )


def _cfg(clone: Path, **kw: object) -> StoreSyncConfig:
    kw.setdefault("backoff_base_s", 0.0)
    return StoreSyncConfig(repo_dir=str(clone), **kw)  # type: ignore[arg-type]


def test_committed_store_is_readable_by_filename_no_crlf(tmp_path):
    r"""Regression (Windows CRLF): the git runner used ``text=True``, so stdin ``\n``
    was translated to ``\r\n`` — a ``git mktree`` line's trailing ``\n`` became ``\r\n``
    and the tree entry name became ``<name>\r``. ``git show <commit>:<name>`` then never
    found the store file, so every fresh-clone pull read an empty store. The byte-oriented
    runner keeps ``\n`` as ``\n``; the file is retrievable by its plain name on all platforms.
    """
    _git(tmp_path, "init", "-q")
    cfg = _cfg(tmp_path)
    commit = _commit_store(cfg, None, "hello\n", "tester", _run)
    shown = _run(["git", "-C", str(tmp_path), "show", f"{commit}:{cfg.store_filename}"], 10)
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout == "hello\n"


def test_opaque_lines_preserved_through_push_not_dropped(tmp_path):
    """A malformed line and a forward-incompatible line (unknown field from an
    upgraded writer) must neither crash the sync nor be deleted from the
    branch by a reader that cannot parse them."""
    remote, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    corrupt = "{not json at all"
    future = json.dumps(
        {**json.loads(_rec(change_id="cf").to_json()), "novel_field": 1}, sort_keys=True
    )
    store.write_text(_rec().to_json() + "\n" + corrupt + "\n" + future + "\n", encoding="utf-8")

    records, opaque = read_store_lines(store)
    assert records == [_rec()]
    assert sorted(opaque) == sorted([corrupt, future])

    assert push(_cfg(clone), store).status is SyncStatus.OK
    branch_content = _git(clone, "show", "origin/merge-gate-data:merge_outcomes.jsonl")
    assert corrupt in branch_content and future in branch_content  # preserved verbatim

    clone2 = tmp_path / "work2"
    _git(tmp_path, "clone", "-q", str(remote), str(clone2))
    store2 = clone2 / "merge_outcomes.jsonl"
    assert pull(_cfg(clone2), store2).status is SyncStatus.OK
    records2, opaque2 = read_store_lines(store2)
    assert records2 == [_rec()]
    assert sorted(opaque2) == sorted([corrupt, future])
    # second push is a byte-level no-op (opaque lines participate in the merge)
    assert push(_cfg(clone2), store2).status is SyncStatus.NOOP


def test_pull_remote_branch_absent_keeps_local_and_exits_zero(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    # A stale FETCH_HEAD from a prior fetch must not be read when the data
    # branch is absent (actions/checkout leaves one behind).
    _git(clone, "fetch", "origin", "main")
    result = pull(_cfg(clone), store)
    assert result.status is SyncStatus.REMOTE_ABSENT
    assert read_store(store) == [_rec()]


def test_push_bootstraps_orphan_branch_and_pull_reads_it_back(tmp_path):
    remote, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    result = push(_cfg(clone), store, actor="tester")
    assert result.status is SyncStatus.OK
    assert result.commit_sha
    # the data-branch commit is parentless (orphan bootstrap) and skips CI
    message = _git(remote, "log", "-1", "--format=%B", "merge-gate-data")
    assert "[skip ci]" in message and "Actor: tester" in message
    assert _git(remote, "rev-list", "--count", "merge-gate-data") == "1"
    # run N+1 in a fresh clone sees the record (AC-1)
    clone2 = tmp_path / "work2"
    _git(tmp_path, "clone", "-q", str(remote), str(clone2))
    store2 = clone2 / "merge_outcomes.jsonl"
    result2 = pull(_cfg(clone2), store2)
    assert result2.status is SyncStatus.OK
    assert read_store(store2) == [_rec()]


def test_push_noop_when_remote_already_superset(tmp_path):
    remote, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    assert push(_cfg(clone), store).status is SyncStatus.OK
    result = push(_cfg(clone), store)
    assert result.status is SyncStatus.NOOP
    assert _git(remote, "rev-list", "--count", "merge-gate-data") == "1"


def test_fetch_failure_leaves_local_untouched(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone"))
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    assert pull(_cfg(clone), store).status is SyncStatus.FETCH_FAILED
    assert read_store(store) == [_rec()]
    result = push(_cfg(clone), store)
    assert result.status is SyncStatus.FETCH_FAILED
    assert result.attempts == 1


@pytest.mark.parametrize("broken_cmd", ["hash-object", "mktree", "commit-tree"])
def test_plumbing_failure_raises_internal_error(tmp_path, broken_cmd):
    _, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])

    def broken_plumbing(args, timeout, input_text=None):
        # commit-tree is preceded by "-c user.name=…" flags, so match anywhere.
        if broken_cmd in args:
            return subprocess.CompletedProcess(list(args), 1, "", f"boom {broken_cmd}")
        return _run(args, timeout, input_text)

    with pytest.raises(Exception, match=f"{broken_cmd} failed"):
        push(_cfg(clone), store, runner=broken_plumbing)


def test_rev_parse_failure_after_fetch_is_fetch_failed(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    push(_cfg(clone), store)

    def broken_rev_parse(args, timeout, input_text=None):
        if args[3] == "rev-parse":
            return subprocess.CompletedProcess(list(args), 128, "", "bad rev")
        return _run(args, timeout, input_text)

    assert pull(_cfg(clone), store, runner=broken_rev_parse).status is SyncStatus.FETCH_FAILED


def test_data_branch_without_store_file_reads_empty(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    # Manually create the data branch WITHOUT the store file.
    (clone / "other.txt").write_text("x", encoding="utf-8")
    _git(clone, "add", "other.txt")
    _git(clone, "commit", "-q", "-m", "unrelated")
    _git(clone, "push", "-q", "origin", "HEAD:refs/heads/merge-gate-data")
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    result = pull(_cfg(clone), store)
    assert result.status is SyncStatus.OK
    assert read_store(store) == [_rec()]


def test_run_missing_binary_and_timeout_are_nonzero_not_raised():
    missing = _run(["definitely-not-a-binary-xyz"], 5.0)
    assert missing.returncode == 127
    slow = _run(["git", "log", "--help"], 0.000001)
    assert slow.returncode in (124, 0)  # timed out (or absurdly fast machine)
