"""Throwaway git repositories for tests that must exercise real git behaviour.

Some properties cannot be faked honestly. "This commit resolves but is not reachable from
HEAD" is one: it needs two real branches and a real object database, because the whole
point of the check under test is that a *resolvable* ref can still be unlanded. A stub that
returns a canned exit code would assert the stub, not the behaviour.

Deliberately test-only, and named with the leading underscore this directory already uses
for support modules (``_m8_probe.py``, ``_matrix_coverage.py``, ``_e2e_matrix.py``). No
production code imports it.

Three sibling test modules — ``test_regression_gate.py``, ``test_protected_paths.py`` and
``test_agent_domain_backfill.py`` — each carry their own private ``_git`` helper predating
this one. Migrating them is a separate, unrelated change; this module is written to be their
replacement when someone does.

The closest prior is ``agent-core/tests/gitrepo.py``, which is near-identical in shape
(same isolation flags, same ``git``/``init_repo``/``commit`` trio) and also carries
``make_remote_and_clone``. It is NOT reused here because ``agent-core/`` is a separate
sub-project with its own rootdir and ``sys.path`` insertion, so a cross-project import is
not available from this suite. Unifying the two belongs with the migration above.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

__all__ = [
    "DEFAULT_BRANCH",
    "GIT_TIMEOUT_SECONDS",
    "checkout",
    "commit",
    "git",
    "head",
    "init_repo",
    "new_branch",
    "shallow_clone",
]

#: Initial branch for a fixture repository. Named rather than inlined so a test can assert
#: against it instead of restating a literal that must match ``init_repo``.
DEFAULT_BRANCH: str = "main"

#: Identity and signing flags passed per-invocation rather than written into the repo's
#: config. A developer machine with ``commit.gpgsign=true`` or no ``user.email`` in its
#: global config would otherwise fail these tests for reasons unrelated to what they check.
_ISOLATION_FLAGS: tuple[str, ...] = (
    "-c",
    "user.email=tests@example.invalid",
    "-c",
    "user.name=Fixture",
    "-c",
    "commit.gpgsign=false",
)

#: Wall-clock bound per invocation. A fixture repository's git commands are local and
#: instant, so anything approaching this is a hang — a credential prompt, a wedged lock —
#: and a hung test is far worse than a failing one: it takes the whole suite with it.
GIT_TIMEOUT_SECONDS: float = 30.0

#: Environment keys scrubbed for every invocation. ``_ISOLATION_FLAGS`` above isolates the
#: repository's *config*; these isolate its *location and behaviour*. A developer (or a CI
#: image) with ``GIT_DIR``/``GIT_WORK_TREE`` exported operates on a different repository
#: entirely despite the ``cwd=`` below, and ``GIT_CONFIG_*``/``GIT_INDEX_FILE`` reintroduce
#: exactly the host config the flags exist to bypass — including ``core.hooksPath`` and
#: ``init.templateDir``, which can run arbitrary code inside a "throwaway" fixture.
_SCRUBBED_ENV: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _isolated_env() -> dict[str, str]:
    """The parent environment with git's location and config overrides removed."""
    env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED_ENV}
    # No prompt can be answered from a test runner; without this a misconfigured remote
    # blocks on stdin until the timeout instead of failing with a usable message.
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(repo: Path, *args: str) -> str:
    """Run git in *repo* and return its stdout, raising on a non-zero exit.

    Raises rather than returning a status: a fixture that half-built itself produces a test
    failure somewhere far away, with a message about the wrong thing.
    """
    result = subprocess.run(
        ["git", *_ISOLATION_FLAGS, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_isolated_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo} ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def init_repo(path: Path, *, branch: str = DEFAULT_BRANCH) -> Path:
    """Create an empty repository at *path* with a deterministic initial branch.

    ``-b`` is explicit because the default branch name is a git *config* value that varies
    by version and by developer machine; a fixture whose branch name depends on the host is
    not a fixture.
    """
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    return path


def commit(repo: Path, message: str, *, filename: str = "file.txt", content: str | None = None) -> str:
    """Write a file, commit it, and return the new commit's full SHA.

    *content* defaults to the message, so successive commits differ without the caller
    having to invent file contents it does not care about.
    """
    (repo / filename).write_text(content if content is not None else f"{message}\n", encoding="utf-8")
    git(repo, "add", filename)
    git(repo, "commit", "-q", "-m", message)
    return head(repo)


def new_branch(repo: Path, name: str) -> None:
    """Create *name* at the current HEAD and check it out."""
    git(repo, "checkout", "-q", "-b", name)


def checkout(repo: Path, name: str) -> None:
    """Check out an existing branch."""
    git(repo, "checkout", "-q", name)


def head(repo: Path) -> str:
    """The full SHA at HEAD."""
    return git(repo, "rev-parse", "HEAD")


def shallow_clone(source: Path, destination: Path, *, depth: int = 1) -> Path:
    """Clone *source* into *destination* with truncated history, and return the clone.

    A real ``--depth`` clone, not a simulated one. The behaviour under test —
    ``scripts/_provenance.py``'s strict-mode downgrade — turns on git reporting
    ``rev-parse --is-shallow-repository == true``, and that string is a *git* fact, not the
    repository's. Stubbing the probe asserts the stub; only a genuinely shallow clone makes
    the branch it guards executable at all.

    ``file://`` rather than a plain path, because git refuses ``--depth`` on a local-path
    clone (it hardlinks the object store instead of fetching) and silently ignores the flag.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", *_ISOLATION_FLAGS, "clone", "-q", "--depth", str(depth), source.resolve().as_uri(), str(destination)],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_isolated_env(),
    )
    return destination
