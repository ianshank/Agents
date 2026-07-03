"""Outcome-store persistence sync against a dedicated git data branch (ADR 0018).

Run as a module:  ``python -m agent_core.store_sync {pull,push,stats} --store <jsonl>``.

The merge-gate outcome store must accumulate records across CI runs, but runner
workspaces are ephemeral. This module syncs the local JSONL store with a single
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
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from .config import ConfigError
from .logging_util import configure_logging, debug_span, get_logger
from .outcome_store import OutcomeRecord

logger = get_logger(__name__)

_DEFAULT_REMOTE = "origin"
_DEFAULT_BRANCH = "merge-gate-data"
_DEFAULT_STORE_FILENAME = "merge_outcomes.jsonl"
_DEFAULT_GIT_TIMEOUT_S = 30.0
_DEFAULT_MAX_PUSH_RETRIES = 5
_DEFAULT_BACKOFF_BASE_S = 0.5
_DEFAULT_COMMIT_NAME = "merge-gate store-sync"
_DEFAULT_COMMIT_EMAIL = "merge-gate-store-sync@users.noreply.github.com"
_COMMIT_MSG_TEMPLATE = "store-sync: {n} records [skip ci]"
_BLOB_MODE = "100644"
# git's message for fetching a ref that does not exist on the remote; used to
# distinguish "branch not born yet" (cold start) from a real fetch failure.
_ABSENT_REF_MARKER = "couldn't find remote ref"
# Conventional shell exit codes for the fail-safe synthetic results (detectors idiom).
_RC_TIMED_OUT = 124
_RC_NOT_FOUND = 127

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_FETCH_FAILED = 4
EXIT_RETRIES_EXHAUSTED = 5


@runtime_checkable
class GitRunner(Protocol):
    """Injectable subprocess seam: run one git command, never raise, never hang."""

    def __call__(
        self, args: Sequence[str], timeout: float, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]: ...


class Sleeper(Protocol):
    """Injectable backoff seam so tests never wall-sleep."""

    def __call__(self, seconds: float, /) -> None: ...


def _run(
    args: Sequence[str], timeout: float, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Fail-safe runner (detectors idiom, plus stdin support for git plumbing):
    a missing binary or a timeout becomes a non-zero result, never an exception."""
    argv = list(args)
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, input=input_text
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, _RC_NOT_FOUND, "", "executable not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, _RC_TIMED_OUT, "", "timed out")


@dataclass(frozen=True)
class StoreSyncConfig:
    """Tunables for the data-branch sync. No literal appears in sync logic."""

    repo_dir: str = "."
    remote: str = _DEFAULT_REMOTE
    branch: str = _DEFAULT_BRANCH
    store_filename: str = _DEFAULT_STORE_FILENAME
    git_timeout_s: float = _DEFAULT_GIT_TIMEOUT_S
    max_push_retries: int = _DEFAULT_MAX_PUSH_RETRIES
    backoff_base_s: float = _DEFAULT_BACKOFF_BASE_S
    commit_user_name: str = _DEFAULT_COMMIT_NAME
    commit_user_email: str = _DEFAULT_COMMIT_EMAIL

    def __post_init__(self) -> None:
        for field_name in (
            "remote",
            "branch",
            "store_filename",
            "commit_user_name",
            "commit_user_email",
        ):
            if not getattr(self, field_name):
                raise ConfigError(f"store_sync.{field_name} must be non-empty")
        # git mktree builds a single tree level, so the store must be a root-level file.
        if "/" in self.store_filename or "\\" in self.store_filename:
            raise ConfigError("store_sync.store_filename must be a root-level filename")
        if self.git_timeout_s <= 0:
            raise ConfigError("store_sync.git_timeout_s must be > 0")
        if self.max_push_retries < 1:
            raise ConfigError("store_sync.max_push_retries must be >= 1")
        if self.backoff_base_s < 0:
            raise ConfigError("store_sync.backoff_base_s must be >= 0")


class SyncStatus(str, Enum):
    OK = "ok"
    NOOP = "noop"  # push: remote already contains every local record
    REMOTE_ABSENT = "remote_absent"  # pull: data branch not born yet (cold start)
    FETCH_FAILED = "fetch_failed"  # remote unreachable; local store untouched
    RETRIES_EXHAUSTED = "retries_exhausted"  # push: concurrent writers kept winning


@dataclass(frozen=True)
class SyncResult:
    status: SyncStatus
    records: int  # records in the merged (or untouched local) store
    attempts: int = 0
    commit_sha: str | None = None


# --- pure merge core ----------------------------------------------------------


def canonical_key(rec: OutcomeRecord) -> tuple[str, bool, str, str, str, str]:
    """Deterministic TOTAL order: pending lines precede labels at the same merge
    time, labels order by ``labeled_at`` — so ``resolved()``'s position-dependent
    "latest labeled wins" is byte-reproducible from any interleaving. The full
    canonical JSON is the final tie-break: without it, records differing only in
    an unkeyed field (e.g. domain) would sort by insertion order."""
    return (
        rec.merged_at,
        rec.labeled_at is not None,
        rec.labeled_at or "",
        rec.label_source or "",
        rec.change_id,
        rec.to_json(),
    )


def merge_records(*sets: Iterable[OutcomeRecord]) -> list[OutcomeRecord]:
    """Union of record sets, deduped by full canonical JSON, canonically sorted.

    Only byte-identical duplicate lines collapse; distinct records for the same
    change (a pending seed, a passive label, a human audit) all survive —
    precedence between them stays ``OutcomeStore.resolved()``'s job.
    """
    unique: dict[str, OutcomeRecord] = {}
    for records in sets:
        for rec in records:
            unique.setdefault(rec.to_json(), rec)
    return sorted(unique.values(), key=canonical_key)


def _parse_line(line: str) -> OutcomeRecord | None:
    """Strictly parse one store line; None means opaque (see merge_opaque).

    A malformed line or one carrying fields this reader doesn't know (an
    upgraded writer during a rolling upgrade) must NOT crash the pipeline —
    and must NOT be silently dropped either, or a subsequent push would
    delete it from the data branch. Opaque lines are preserved verbatim.
    """
    try:
        return OutcomeRecord(**json.loads(line))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("store-sync preserving unparseable line (%s): %.120s", exc, line)
        return None


def _split_lines(text: str) -> tuple[list[OutcomeRecord], list[str]]:
    records: list[OutcomeRecord] = []
    opaque: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        rec = _parse_line(line)
        if rec is None:
            opaque.append(line)
        else:
            records.append(rec)
    return records, opaque


def merge_opaque(*sets: Iterable[str]) -> list[str]:
    """Union of opaque (unparseable-here) lines, deduped exactly, sorted.

    They serialize AFTER the parsed records: their canonical position cannot
    be computed without parsing, and the next upgraded writer re-canonicalizes
    the whole store anyway.
    """
    unique: set[str] = set()
    for lines in sets:
        unique.update(lines)
    return sorted(unique)


def serialize_store(records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()) -> str:
    body = "".join(rec.to_json() + "\n" for rec in records)
    return body + "".join(line + "\n" for line in opaque)


def read_store_lines(path: str | Path) -> tuple[list[OutcomeRecord], list[str]]:
    """(records, opaque lines) of the local store; absent file is empty."""
    target = Path(path)
    if not target.exists():
        return [], []
    return _split_lines(target.read_text(encoding="utf-8"))


def read_store(path: str | Path) -> list[OutcomeRecord]:
    """Parsed records in the local store; an absent file is an empty store."""
    return read_store_lines(path)[0]


def write_store(
    path: str | Path, records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()
) -> None:
    """Atomically replace the local store with the canonical serialization."""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(serialize_store(records, opaque), encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


# Reserved stats key for lines this reader could not parse (observability —
# real domains come from config/merge-gate-domains.yaml and never start with _).
UNPARSED_STATS_KEY = "_unparsed"


def store_stats(
    records: Sequence[OutcomeRecord], opaque: Sequence[str] = ()
) -> dict[str, dict[str, int]]:
    """Per-domain counts by label source over RAW lines (accumulation view):
    ``{domain: {"pending" | <label_source>: count}}`` plus ``_unparsed`` lines."""
    stats: dict[str, dict[str, int]] = {}
    for rec in records:
        source = rec.label_source if rec.label_source is not None else "pending"
        domain = stats.setdefault(rec.domain, {})
        domain[source] = domain.get(source, 0) + 1
    if opaque:
        stats[UNPARSED_STATS_KEY] = {"lines": len(opaque)}
    return stats


# --- git layer ----------------------------------------------------------------


class StoreSyncGitError(RuntimeError):
    """A git plumbing command that should always succeed did not."""


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


# --- CLI ------------------------------------------------------------------------

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


if __name__ == "__main__":
    sys.exit(main())
