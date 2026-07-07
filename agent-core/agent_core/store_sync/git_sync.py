"""Git plumbing layer and the pull/push orchestration for the data-branch sync.

Commits are built with ``hash-object``/``mktree``/``commit-tree`` so the
checked-out worktree and index are never touched. The fetch return code gates
every ``FETCH_HEAD`` read (CI checkouts leave a stale one behind). See the
package docstring for the exit-code contract.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from ..logging_util import debug_span, get_logger
from ..outcome_store import OutcomeRecord
from ..subprocess_util import run_failsafe
from .models import GitRunner, Sleeper, StoreSyncConfig, StoreSyncGitError, SyncResult, SyncStatus
from .serialization import _split_lines, merge_opaque, merge_records, serialize_store
from .store import read_store, read_store_lines, write_store

logger = get_logger(__name__)

_COMMIT_MSG_TEMPLATE = "store-sync: {n} records [skip ci]"
_BLOB_MODE = "100644"
# git's message for fetching a ref that does not exist on the remote; used to
# distinguish "branch not born yet" (cold start) from a real fetch failure.
_ABSENT_REF_MARKER = "couldn't find remote ref"

# Shared fail-safe runner (:mod:`agent_core.subprocess_util`), bound as a module attribute so
# the CLI + tests keep monkeypatching ``agent_core.store_sync._run``. It supports the
# ``input_text`` stdin payload the git plumbing commits need.
_run = run_failsafe


def _git(
    cfg: StoreSyncConfig,
    args: Sequence[str],
    runner: GitRunner,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return runner(["git", "-C", cfg.repo_dir, *args], cfg.git_timeout_s, input_text)


def _fetch_tip(cfg: StoreSyncConfig, runner: GitRunner) -> tuple[SyncStatus, str | None]:
    """Fetch the data branch and return its tip.

    The fetch return code gates everything: only after a successful fetch is
    ``FETCH_HEAD`` read (CI checkouts leave a stale one behind). An absent remote
    ref is REMOTE_ABSENT (cold start); any other failure is FETCH_FAILED.
    """
    proc = _git(cfg, ["fetch", "--no-tags", cfg.remote, cfg.branch], runner)
    if proc.returncode != 0:
        if _ABSENT_REF_MARKER in proc.stderr.lower():
            logger.info("store-sync remote branch %s absent (cold start)", cfg.branch)
            return SyncStatus.REMOTE_ABSENT, None
        logger.warning(
            "store-sync fetch failed rc=%s stderr=%s", proc.returncode, proc.stderr.strip()
        )
        return SyncStatus.FETCH_FAILED, None
    tip = _git(cfg, ["rev-parse", "FETCH_HEAD"], runner)
    if tip.returncode != 0:
        logger.warning("store-sync rev-parse FETCH_HEAD failed: %s", tip.stderr.strip())
        return SyncStatus.FETCH_FAILED, None
    return SyncStatus.OK, tip.stdout.strip()


def _read_remote_lines(
    cfg: StoreSyncConfig, tip: str, runner: GitRunner
) -> tuple[list[OutcomeRecord], list[str]]:
    """(records, opaque lines) of the store file at *tip*. The fetch already
    succeeded, so a ``git show`` failure here means the file is absent -> empty."""
    proc = _git(cfg, ["show", f"{tip}:{cfg.store_filename}"], runner)
    if proc.returncode != 0:
        # Diagnosable absent-vs-error: the fetch already succeeded, so this is
        # almost always "file not in that commit", but keep the evidence.
        logger.debug(
            "store-sync show %s:%s rc=%s stderr=%s -> empty store",
            tip,
            cfg.store_filename,
            proc.returncode,
            proc.stderr.strip(),
        )
        return [], []
    return _split_lines(proc.stdout)


def _commit_store(
    cfg: StoreSyncConfig,
    parent: str | None,
    content: str,
    actor: str | None,
    runner: GitRunner,
) -> str:
    """Commit *content* as the store file via plumbing; never touches the worktree."""
    blob = _git(cfg, ["hash-object", "-w", "--stdin"], runner, input_text=content)
    if blob.returncode != 0:
        raise StoreSyncGitError(f"hash-object failed: {blob.stderr.strip()}")
    tree = _git(
        cfg,
        ["mktree"],
        runner,
        input_text=f"{_BLOB_MODE} blob {blob.stdout.strip()}\t{cfg.store_filename}\n",
    )
    if tree.returncode != 0:
        raise StoreSyncGitError(f"mktree failed: {tree.stderr.strip()}")
    n = content.count("\n")
    message = _COMMIT_MSG_TEMPLATE.format(n=n)
    if actor:
        message += f"\n\nActor: {actor}"
    # Runners have no git ident; commit-tree fails with "empty ident" without -c.
    args = [
        "-c",
        f"user.name={cfg.commit_user_name}",
        "-c",
        f"user.email={cfg.commit_user_email}",
        "commit-tree",
        tree.stdout.strip(),
    ]
    if parent is not None:
        args += ["-p", parent]
    args += ["-m", message]
    commit = _git(cfg, args, runner)
    if commit.returncode != 0:
        raise StoreSyncGitError(f"commit-tree failed: {commit.stderr.strip()}")
    return commit.stdout.strip()


def pull(cfg: StoreSyncConfig, store_path: str | Path, runner: GitRunner = _run) -> SyncResult:
    """Merge remote records into the local store. Never pushes.

    REMOTE_ABSENT keeps the local store as-is (cold start is not an error);
    FETCH_FAILED leaves it untouched so a flaky remote cannot corrupt state.
    """
    with debug_span(logger, "store_sync.pull", branch=cfg.branch):
        status, tip = _fetch_tip(cfg, runner)
        local, local_opaque = read_store_lines(store_path)
        if status is not SyncStatus.OK or tip is None:
            return SyncResult(status=status, records=len(local))
        remote, remote_opaque = _read_remote_lines(cfg, tip, runner)
        merged = merge_records(remote, local)
        opaque = merge_opaque(remote_opaque, local_opaque)
        write_store(store_path, merged, opaque)
        logger.info(
            "store-sync pull merged %d records (+%d opaque lines) from %s",
            len(merged),
            len(opaque),
            cfg.branch,
        )
        return SyncResult(status=SyncStatus.OK, records=len(merged))


def push(
    cfg: StoreSyncConfig,
    store_path: str | Path,
    actor: str | None = None,
    runner: GitRunner = _run,
    sleeper: Sleeper = time.sleep,
) -> SyncResult:
    """Publish the union of remote + local records to the data branch.

    Retry loop: a rejected push means a concurrent writer won — refetch,
    re-merge (our records survive the union), back off exponentially, retry.
    A fetch failure aborts immediately: retrying a push on a stale base is
    pointless when the remote is unreachable.
    """
    with debug_span(logger, "store_sync.push", branch=cfg.branch):
        attempts = 0
        for attempt in range(cfg.max_push_retries):
            attempts = attempt + 1
            status, tip = _fetch_tip(cfg, runner)
            if status is SyncStatus.FETCH_FAILED:
                return SyncResult(
                    status=status, records=len(read_store(store_path)), attempts=attempts
                )
            if tip is not None:
                remote, remote_opaque = _read_remote_lines(cfg, tip, runner)
            else:
                remote, remote_opaque = [], []
            local, local_opaque = read_store_lines(store_path)
            merged = merge_records(remote, local)
            opaque = merge_opaque(remote_opaque, local_opaque)
            content = serialize_store(merged, opaque)
            if content == serialize_store(remote, remote_opaque):
                logger.info("store-sync push no-op: remote already has all %d records", len(merged))
                return SyncResult(status=SyncStatus.NOOP, records=len(merged), attempts=attempts)
            write_store(store_path, merged, opaque)  # keep the local store canonical too
            commit = _commit_store(cfg, tip, content, actor, runner)
            pushed = _git(cfg, ["push", cfg.remote, f"{commit}:refs/heads/{cfg.branch}"], runner)
            if pushed.returncode == 0:
                logger.info(
                    "store-sync pushed %d records to %s (attempt %d, commit %s)",
                    len(merged),
                    cfg.branch,
                    attempts,
                    commit,
                )
                return SyncResult(
                    status=SyncStatus.OK, records=len(merged), attempts=attempts, commit_sha=commit
                )
            logger.warning(
                "store-sync push rejected remote=%s branch=%s commit=%s (attempt %d/%d): %s",
                cfg.remote,
                cfg.branch,
                commit,
                attempts,
                cfg.max_push_retries,
                pushed.stderr.strip(),
            )
            if attempt < cfg.max_push_retries - 1:
                sleeper(cfg.backoff_base_s * (2**attempt))
        return SyncResult(
            status=SyncStatus.RETRIES_EXHAUSTED,
            records=len(read_store(store_path)),
            attempts=attempts,
        )
