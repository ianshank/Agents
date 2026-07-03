"""Shared real-git helpers for the test suite (no mocks — see test_detectors).

Importable as a plain module because pytest puts this directory on ``sys.path``
(rootdir insertion; the suite has no ``__init__.py``). Shared by
``test_detectors.py`` and ``test_store_sync.py`` so the identity/config flags
stay single-sourced.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_IDENT_FLAGS = (
    "-c",
    "user.email=t@e",
    "-c",
    "user.name=t",
    "-c",
    "commit.gpgsign=false",
)


def git(cwd: Path, *args: str) -> str:
    """Run git in *cwd* with a throwaway ident; assert success, return stdout."""
    proc = subprocess.run(
        ["git", *_IDENT_FLAGS, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    return path


def commit(path: Path, name: str, content: str, message: str) -> str:
    (path / name).write_text(content, encoding="utf-8")
    git(path, "add", name)
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


def make_remote_and_clone(tmp_path: Path, name: str = "work") -> tuple[Path, Path]:
    """A bare remote with a born ``main`` plus a clone of it."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "-q", "--bare", "-b", "main")
    seedwork = init_repo(tmp_path / "_seedwork")
    commit(seedwork, "README", "x", "init")
    git(seedwork, "remote", "add", "origin", str(remote))
    git(seedwork, "push", "-q", "origin", "main")
    clone = tmp_path / name
    git(tmp_path, "clone", "-q", str(remote), str(clone))
    return remote, clone
