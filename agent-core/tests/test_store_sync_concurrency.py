"""Tests for store_sync — concurrency injection and CLI execution.

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
    EXIT_FETCH_FAILED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_RETRIES_EXHAUSTED,
    StoreSyncConfig,
    SyncStatus,
    _run,
    main,
    pull,
    push,
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


def test_push_merges_after_concurrent_competitor_and_retries(tmp_path):
    remote, clone_a = _make_remote_and_clone(tmp_path, name="work_a")
    clone_b = tmp_path / "work_b"
    _git(tmp_path, "clone", "-q", str(remote), str(clone_b))
    store_a = clone_a / "merge_outcomes.jsonl"
    store_b = clone_b / "merge_outcomes.jsonl"
    write_store(store_a, [_rec(change_id="ca")])
    write_store(store_b, [_rec(change_id="cb")])

    sleeps: list[float] = []
    competitor_done = False

    def racing_runner(args, timeout, input_text=None):
        # Inject the competitor's push between A's fetch and A's push.
        nonlocal competitor_done
        if not competitor_done and args[3] == "push":
            competitor_done = True
            assert push(_cfg(clone_b), store_b).status is SyncStatus.OK
        return _run(args, timeout, input_text)

    cfg = _cfg(clone_a, backoff_base_s=0.25)
    result = push(cfg, store_a, runner=racing_runner, sleeper=sleeps.append)
    assert result.status is SyncStatus.OK
    assert result.attempts == 2
    assert sleeps == [0.25]  # backoff_base * 2**0, recorded — never wall-slept
    clone_c = tmp_path / "work_c"
    _git(tmp_path, "clone", "-q", str(remote), str(clone_c))
    final = pull(_cfg(clone_c), clone_c / "merge_outcomes.jsonl")
    assert final.records == 2  # both writers' records survive (AC-2)


def test_push_exhausts_retries_when_competitor_always_wins(tmp_path):
    remote, clone_a = _make_remote_and_clone(tmp_path, name="work_a")
    clone_b = tmp_path / "work_b"
    _git(tmp_path, "clone", "-q", str(remote), str(clone_b))
    store_a = clone_a / "merge_outcomes.jsonl"
    write_store(store_a, [_rec(change_id="ca")])

    n = 0

    def always_beaten_runner(args, timeout, input_text=None):
        nonlocal n
        if args[3] == "push":
            n += 1
            write_store(clone_b / "merge_outcomes.jsonl", [_rec(change_id=f"cb{n}")])
            assert push(_cfg(clone_b), clone_b / "merge_outcomes.jsonl").status is SyncStatus.OK
        return _run(args, timeout, input_text)

    sleeps: list[float] = []
    cfg = _cfg(clone_a, max_push_retries=3, backoff_base_s=1.0)
    result = push(cfg, store_a, runner=always_beaten_runner, sleeper=sleeps.append)
    assert result.status is SyncStatus.RETRIES_EXHAUSTED
    assert result.attempts == 3
    assert sleeps == [1.0, 2.0]  # exponential sequence, no sleep after the last attempt


def test_cli_pull_push_stats_and_exit_codes(tmp_path, capsys):
    _, clone = _make_remote_and_clone(tmp_path)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    # Options come AFTER the subcommand — the invocation order the workflows use.
    base = ["--store", str(store), "--repo-dir", str(clone), "--backoff", "0"]
    assert main(["push", *base, "--actor", "ci"]) == EXIT_OK
    assert main(["pull", *base]) == EXIT_OK
    assert main(["stats", *base]) == EXIT_OK
    out = capsys.readouterr().out
    assert "STORE_SYNC=ok" in out
    assert json.loads(out.strip().splitlines()[-1]) == {"human/agent-core": {"pending": 1}}
    _git(clone, "remote", "set-url", "origin", str(tmp_path / "gone"))
    assert main(["pull", *base]) == EXIT_FETCH_FAILED
    assert main(["push", *base]) == EXIT_FETCH_FAILED


def test_cli_retries_exhausted_exit_code(tmp_path, monkeypatch):
    remote, clone_a = _make_remote_and_clone(tmp_path, name="work_a")
    clone_b = tmp_path / "work_b"
    _git(tmp_path, "clone", "-q", str(remote), str(clone_b))
    store_a = clone_a / "merge_outcomes.jsonl"
    write_store(store_a, [_rec(change_id="ca")])

    n = 0
    real_run = _run

    def always_beaten(args, timeout, input_text=None):
        # clone_b's competitor pushes go through push()'s def-time default
        # runner (the real _run), so this wrapper never recurses.
        nonlocal n
        if len(args) > 3 and args[3] == "push" and str(clone_a) in args[2]:
            n += 1
            write_store(clone_b / "merge_outcomes.jsonl", [_rec(change_id=f"cb{n}")])
            push(_cfg(clone_b), clone_b / "merge_outcomes.jsonl")
        return real_run(args, timeout, input_text)

    monkeypatch.setattr("agent_core.store_sync._run", always_beaten)
    base = [
        "--store",
        str(store_a),
        "--repo-dir",
        str(clone_a),
        "--max-retries",
        "2",
        "--backoff",
        "0",
    ]
    assert main(["push", *base]) == EXIT_RETRIES_EXHAUSTED


def test_cli_internal_error_and_usage(tmp_path, capsys, monkeypatch):
    _, clone = _make_remote_and_clone(tmp_path)

    def broken(args, timeout, input_text=None):
        if len(args) > 3 and args[3] == "hash-object":
            return subprocess.CompletedProcess(list(args), 1, "", "boom")
        return _run(args, timeout, input_text)

    monkeypatch.setattr("agent_core.store_sync._run", broken)
    store = clone / "merge_outcomes.jsonl"
    write_store(store, [_rec()])
    rc = main(["push", "--store", str(store), "--repo-dir", str(clone)])
    assert rc == EXIT_INTERNAL
    assert "internal error" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["push"])  # missing required --store
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        main([])  # missing subcommand
    assert exc.value.code == 2
