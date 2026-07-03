"""Tests for store_sync — real git repositories (bare remotes + clones), no mocks.

Concurrency is exercised with a competitor clone whose pushes are injected via a
wrapping GitRunner; backoff uses a recording sleeper so nothing wall-sleeps.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# Real-git helpers shared with test_detectors (tests/gitrepo.py).
from gitrepo import git as _git
from gitrepo import make_remote_and_clone as _make_remote_and_clone
from hypothesis import given
from hypothesis import strategies as st

from agent_core.config import ConfigError
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from agent_core.store_sync import (
    EXIT_FETCH_FAILED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_RETRIES_EXHAUSTED,
    UNPARSED_STATS_KEY,
    StoreSyncConfig,
    SyncStatus,
    _run,
    canonical_key,
    main,
    merge_records,
    pull,
    push,
    read_store,
    read_store_lines,
    serialize_store,
    store_stats,
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


# --- config validation ---------------------------------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"remote": ""},
        {"branch": ""},
        {"store_filename": ""},
        {"store_filename": "data/store.jsonl"},
        {"store_filename": "data\\store.jsonl"},
        {"git_timeout_s": 0},
        {"max_push_retries": 0},
        {"backoff_base_s": -1.0},
        {"commit_user_name": ""},
        {"commit_user_email": ""},
    ],
)
def test_config_validation_raises_config_error(kw):
    with pytest.raises(ConfigError):
        StoreSyncConfig(**kw)


# --- pure merge core -----------------------------------------------------------
def test_canonical_key_orders_pending_before_labels():
    pending = _rec()
    labeled = _rec(label=False, label_source="revert", labeled_at="2026-01-02T00:00:00+00:00")
    assert canonical_key(pending) < canonical_key(labeled)


def test_merge_records_dedupes_identical_lines_and_keeps_distinct_labels():
    pending = _rec()
    rev = _rec(label=False, label_source="revert", labeled_at="2026-01-02T00:00:00+00:00")
    merged = merge_records([pending, rev], [pending])
    assert merged == [pending, rev]


def test_serialize_store_byte_stable_under_shuffle():
    records = [
        _rec(change_id=c, labeled_at=la, label_source=ls, label=lb)
        for c, la, ls, lb in [
            ("c1", None, None, None),
            ("c2", "2026-01-03T00:00:00+00:00", "timeout_clean", True),
            ("c1", "2026-01-02T00:00:00+00:00", "revert", False),
        ]
    ]
    a = serialize_store(merge_records(records))
    b = serialize_store(merge_records(reversed(records)))
    assert a == b


def test_read_store_absent_file_is_empty(tmp_path):
    assert read_store(tmp_path / "nope.jsonl") == []


def test_write_store_atomic_and_propagates_failure(tmp_path):
    path = tmp_path / "s.jsonl"
    write_store(path, [_rec()])
    assert read_store(path) == [_rec()]
    with pytest.raises(OSError):
        write_store(tmp_path / "missing-dir" / "s.jsonl", [_rec()])


def test_stats_counts_per_domain_per_source_including_pending(tmp_path):
    path = tmp_path / "s.jsonl"
    write_store(
        path,
        [
            _rec(change_id="c1"),
            _rec(
                change_id="c1",
                label=False,
                label_source="revert",
                labeled_at="2026-01-02T00:00:00+00:00",
            ),
            _rec(change_id="c2", domain="human/docs"),
        ],
    )
    assert store_stats(read_store(path)) == {
        "human/agent-core": {"pending": 1, "revert": 1},
        "human/docs": {"pending": 1},
    }


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


def test_stats_reports_unparsed_lines(tmp_path):
    store = tmp_path / "s.jsonl"
    store.write_text(_rec().to_json() + "\n\n" + "{broken\n", encoding="utf-8")
    records, opaque = read_store_lines(store)
    stats = store_stats(records, opaque)
    assert stats[UNPARSED_STATS_KEY] == {"lines": 1}
    assert stats["human/agent-core"] == {"pending": 1}


# --- hypothesis: merge properties ------------------------------------------------
_records_strategy = st.lists(
    st.builds(
        _rec,
        change_id=st.sampled_from(["c1", "c2", "c3"]),
        domain=st.sampled_from(["human/a", "human/b"]),
        merged_at=st.sampled_from(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]),
        label=st.sampled_from([True, False]),
        label_source=st.sampled_from([s.value for s in LabelSource]),
        labeled_at=st.sampled_from(["2026-01-03T00:00:00+00:00", "2026-01-04T00:00:00+00:00"]),
    )
    | st.builds(
        _rec,
        change_id=st.sampled_from(["c1", "c2", "c3"]),
        domain=st.sampled_from(["human/a", "human/b"]),
        merged_at=st.sampled_from(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]),
    ),
    max_size=12,
)


@given(a=_records_strategy, b=_records_strategy)
def test_merge_idempotent_and_commutative(a, b):
    ab = serialize_store(merge_records(a, b))
    ba = serialize_store(merge_records(b, a))
    again = serialize_store(merge_records(merge_records(a, b), a))
    assert ab == ba == again


@given(records=_records_strategy, data=st.data())
def test_any_interleaving_yields_identical_store_and_resolved_view(tmp_path_factory, records, data):
    permutation = data.draw(st.permutations(records))
    cut = data.draw(st.integers(min_value=0, max_value=len(records)))
    merged_a = merge_records(records)
    merged_b = merge_records(list(permutation)[:cut], list(permutation)[cut:])
    assert serialize_store(merged_a) == serialize_store(merged_b)
    base = tmp_path_factory.mktemp("interleave")
    pa, pb = base / "a.jsonl", base / "b.jsonl"
    write_store(pa, merged_a)
    write_store(pb, merged_b)
    assert OutcomeStore(pa).resolved() == OutcomeStore(pb).resolved()


@given(a=_records_strategy, b=_records_strategy)
def test_human_audit_records_never_dropped_and_still_win(tmp_path_factory, a, b):
    merged = merge_records(a, b)
    human = [r for r in a + b if r.label_source == LabelSource.HUMAN_AUDIT.value]
    for rec in human:
        assert rec in merged
    path = tmp_path_factory.mktemp("human") / "s.jsonl"
    write_store(path, merged)
    resolved = OutcomeStore(path).resolved()
    for rec in human:
        assert resolved[rec.change_id].label_source == LabelSource.HUMAN_AUDIT.value


# --- git layer against real repositories ----------------------------------------
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


# --- fail-safe runner -----------------------------------------------------------
def test_run_missing_binary_and_timeout_are_nonzero_not_raised():
    missing = _run(["definitely-not-a-binary-xyz"], 5.0)
    assert missing.returncode == 127
    slow = _run(["git", "log", "--help"], 0.000001)
    assert slow.returncode in (124, 0)  # timed out (or absurdly fast machine)


# --- CLI --------------------------------------------------------------------------
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
