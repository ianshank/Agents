"""Value types and tunables for the outcome-store data-branch sync (ADR 0018).

No literal appears in sync logic: every default lives here as a module constant,
surfaced through :class:`StoreSyncConfig`. See the package docstring for the
overall design and correctness properties.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ..config import ConfigError

_DEFAULT_REMOTE = "origin"
_DEFAULT_BRANCH = "merge-gate-data"
_DEFAULT_STORE_FILENAME = "merge_outcomes.jsonl"
_DEFAULT_GIT_TIMEOUT_S = 30.0
_DEFAULT_MAX_PUSH_RETRIES = 5
_DEFAULT_BACKOFF_BASE_S = 0.5
_DEFAULT_COMMIT_NAME = "merge-gate store-sync"
_DEFAULT_COMMIT_EMAIL = "merge-gate-store-sync@users.noreply.github.com"

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


class StoreSyncGitError(RuntimeError):
    """A git plumbing command that should always succeed did not."""
