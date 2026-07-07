"""Outcome-store persistence sync against a dedicated git data branch (ADR 0018).

Run as a module:  ``python -m agent_core.store_sync {pull,push,stats} --store <jsonl>``.

The merge-gate outcome store must accumulate records across CI runs, but runner
workspaces are ephemeral. This package syncs the local JSONL store with a single
root-level file on a dedicated branch (default ``merge-gate-data``):

  * ``pull``  — fetch the remote branch and merge its records into the local store.
                An absent remote branch is cold start, not an error.
  * ``push``  — fetch, merge remote + local, commit the union with git plumbing
                (``hash-object``/``mktree``/``commit-tree`` — the checked-out worktree
                and index are never touched) and push, retrying with exponential
                backoff when a concurrent writer wins the race.
  * ``stats`` — per-domain / per-label-source record counts (observability).

Correctness properties (ADR 0018):
  * The merged store is written in a canonical deterministic order, because
    ``OutcomeStore.resolved()`` resolves passive labels by file position — any
    interleaving of the same record sets must yield a byte-identical store.
  * Deduplication is by the full canonical record JSON: only byte-identical
    duplicate lines are dropped; a ``HUMAN_AUDIT`` line is never discarded.
  * The fetch return code is checked BEFORE ``FETCH_HEAD`` is read: CI checkouts
    leave a stale ``FETCH_HEAD`` behind, and an unguarded read would silently use
    the wrong commit.

Exit codes (stable contract for CI):
  0  success — pull OK / remote branch absent (cold start), push OK / no-op, stats
  4  fetch failed (remote unreachable) — local store left untouched
  5  push retries exhausted (concurrent writers kept winning)
  2  usage error (argparse);  1 unexpected internal error

The implementation is split across ``models`` (value types + tunables),
``serialization`` (pure merge core), ``store`` (local file I/O + stats), and
``git_sync`` (git plumbing + pull/push). This module re-exports the full public
surface so ``from agent_core.store_sync import X`` keeps working unchanged, and
keeps the CLI ``main`` here so the module-attribute ``_run`` seam stays patchable.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..logging_util import configure_logging

# The ``X as X`` redundant-alias form marks these as explicit re-exports (mypy
# no_implicit_reexport): the CLI resolves ``_run`` at call time, tests monkeypatch
# ``agent_core.store_sync._run``, and the git-plumbing tests import ``_commit_store``
# directly from the package — all part of the backwards-compatible public surface.
from .git_sync import _commit_store as _commit_store
from .git_sync import _run as _run
from .git_sync import pull, push
from .models import (
    _DEFAULT_BACKOFF_BASE_S,
    _DEFAULT_BRANCH,
    _DEFAULT_GIT_TIMEOUT_S,
    _DEFAULT_MAX_PUSH_RETRIES,
    _DEFAULT_REMOTE,
    EXIT_FETCH_FAILED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_RETRIES_EXHAUSTED,
    GitRunner,
    Sleeper,
    StoreSyncConfig,
    StoreSyncGitError,
    SyncResult,
    SyncStatus,
)
from .serialization import (
    canonical_key,
    merge_opaque,
    merge_records,
    serialize_store,
)
from .store import (
    UNPARSED_STATS_KEY,
    read_store,
    read_store_lines,
    store_stats,
    write_store,
)

__all__ = [
    "EXIT_FETCH_FAILED",
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_RETRIES_EXHAUSTED",
    "UNPARSED_STATS_KEY",
    "GitRunner",
    "Sleeper",
    "StoreSyncConfig",
    "StoreSyncGitError",
    "SyncResult",
    "SyncStatus",
    "canonical_key",
    "main",
    "merge_opaque",
    "merge_records",
    "pull",
    "push",
    "read_store",
    "read_store_lines",
    "serialize_store",
    "store_stats",
    "write_store",
]

_EXIT_BY_STATUS = {
    SyncStatus.OK: EXIT_OK,
    SyncStatus.NOOP: EXIT_OK,
    SyncStatus.REMOTE_ABSENT: EXIT_OK,
    SyncStatus.FETCH_FAILED: EXIT_FETCH_FAILED,
    SyncStatus.RETRIES_EXHAUSTED: EXIT_RETRIES_EXHAUSTED,
}


def _config_from_args(args: argparse.Namespace) -> StoreSyncConfig:
    return StoreSyncConfig(
        repo_dir=args.repo_dir,
        remote=args.remote,
        branch=args.branch,
        git_timeout_s=args.timeout,
        max_push_retries=args.max_retries,
        backoff_base_s=args.backoff,
    )


def main(argv: list[str] | None = None) -> int:
    # Common options live on the SUBCOMMANDS (via a parent parser) so the
    # natural invocation order `store_sync push --store …` works — with
    # top-level-only options, everything after the subcommand is rejected.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", required=True, help="local outcome-store JSONL path")
    common.add_argument("--repo-dir", default=".", help="git repository directory")
    common.add_argument("--remote", default=_DEFAULT_REMOTE)
    common.add_argument("--branch", default=_DEFAULT_BRANCH)
    common.add_argument("--timeout", type=float, default=_DEFAULT_GIT_TIMEOUT_S)
    common.add_argument("--max-retries", type=int, default=_DEFAULT_MAX_PUSH_RETRIES)
    common.add_argument("--backoff", type=float, default=_DEFAULT_BACKOFF_BASE_S)
    ap = argparse.ArgumentParser(description="Outcome-store data-branch sync (ADR 0018).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", parents=[common], help="merge the remote store into the local store")
    p_push = sub.add_parser(
        "push", parents=[common], help="publish merged records to the data branch"
    )
    p_push.add_argument("--actor", help="attribution trailer for the data-branch commit")
    sub.add_parser(
        "stats", parents=[common], help="per-domain / per-label-source record counts (JSON)"
    )
    args = ap.parse_args(argv)

    configure_logging(level="INFO")
    try:
        if args.cmd == "stats":
            records, opaque = read_store_lines(args.store)
            print(json.dumps(store_stats(records, opaque), sort_keys=True))
            return EXIT_OK
        cfg = _config_from_args(args)
        # Resolve the runner at call time (module attribute) so the seam stays
        # injectable for tests exercising the CLI entry path.
        if args.cmd == "pull":
            result = pull(cfg, args.store, runner=_run)
        else:
            result = push(cfg, args.store, actor=args.actor, runner=_run)
    except Exception as exc:  # unexpected -> exit 1, never silently pass
        print(f"store-sync internal error: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    print(f"STORE_SYNC={result.status.value} records={result.records} attempts={result.attempts}")
    return _EXIT_BY_STATUS[result.status]
