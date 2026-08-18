"""Locate an OpenSpec change directory and read its task-completion state.

Two responsibilities live here, and only here, so every other module (and the tests) can
treat "which change, in what state" as a single, already-resolved fact:

1. **Locate** ``openspec/changes/<id>/`` for an explicit id, or infer one from the current
   git branch name / recent commit subjects when the caller did not name one.
2. **Read** ``tasks.md`` well enough to answer "does this look done" — a checkbox count, not
   a judgement about whether the right things were checked.

Git access is isolated behind two small functions (:func:`current_branch_name`,
:func:`recent_commit_subjects`) that accept an injectable ``run`` callable, so tests never
need a real git repository or subprocess mocking to exercise the inference logic.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: ``- [ ]`` / ``- [x]`` / ``- [X]`` at the start of a (possibly indented) list item. Matches
#: only the checkbox itself — a same-line ``[P]`` protected-path marker (this repo's own
#: tasks.md convention) always follows a closing bracket and backtick, so it never collides.
_CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s+(.*)$", re.MULTILINE)

#: Default number of recent commit subjects scanned for a change id when the branch name
#: itself doesn't match one.
DEFAULT_COMMIT_SCAN_DEPTH = 20

_GIT_TIMEOUT_SECONDS = 10


class ChangeNotFoundError(Exception):
    """Raised when no OpenSpec change directory can be located or inferred."""


@dataclass(frozen=True)
class TaskStatus:
    """Checkbox tally for one ``tasks.md`` file."""

    total: int
    checked: int
    unchecked_items: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """True only when at least one checkbox exists and every one is checked."""
        return self.total > 0 and self.checked == self.total

    @property
    def fraction_complete(self) -> float:
        return (self.checked / self.total) if self.total else 0.0


@dataclass(frozen=True)
class ChangeLocation:
    """A resolved OpenSpec change: where it lives, and how ready it looks."""

    change_id: str
    change_dir: Path
    inferred: bool
    inferred_from: str | None
    tasks_status: TaskStatus | None
    review_path: Path
    review_exists: bool


def parse_tasks_status(text: str, *, unchecked_limit: int = 5) -> TaskStatus:
    """Tally ``- [ ]``/``- [x]`` checkboxes in *text*.

    ``unchecked_limit`` caps how many unchecked item texts are retained for reporting —
    callers that need the full list can re-scan ``text`` themselves; this exists only to keep
    a CLI report readable when dozens of boxes are unchecked.
    """
    boxes = _CHECKBOX_RE.findall(text)
    checked = sum(1 for mark, _ in boxes if mark.lower() == "x")
    unchecked = tuple(item.strip() for mark, item in boxes if mark.lower() != "x")
    return TaskStatus(total=len(boxes), checked=checked, unchecked_items=unchecked[:unchecked_limit])


def list_change_ids(changes_root: Path) -> tuple[str, ...]:
    """Sorted directory names under ``changes_root``, excluding ``archive``."""
    if not changes_root.is_dir():
        return ()
    return tuple(sorted(p.name for p in changes_root.iterdir() if p.is_dir() and p.name != "archive"))


def _run_git(repo_root: Path, args: Sequence[str]) -> str | None:
    """Run a git subcommand in *repo_root*; return stripped stdout, or None on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def current_branch_name(repo_root: Path, *, run: Callable[[Path, Sequence[str]], str | None] = _run_git) -> str | None:
    """The repo's current branch name, or None if unavailable (detached HEAD, not a git repo, ...)."""
    name = run(repo_root, ["branch", "--show-current"])
    return name or None


def recent_commit_subjects(
    repo_root: Path,
    *,
    count: int = DEFAULT_COMMIT_SCAN_DEPTH,
    run: Callable[[Path, Sequence[str]], str | None] = _run_git,
) -> tuple[str, ...]:
    """The last *count* commit subject lines, most recent first. Empty tuple if unavailable."""
    out = run(repo_root, ["log", f"-{count}", "--format=%s"])
    if not out:
        return ()
    return tuple(out.splitlines())


def current_tree_sha(repo_root: Path, *, run: Callable[[Path, Sequence[str]], str | None] = _run_git) -> str | None:
    """``git rev-parse HEAD`` in *repo_root*, or None if unavailable."""
    return run(repo_root, ["rev-parse", "HEAD"])


def _match_id_in_text(candidate_ids: Sequence[str], text: str) -> str | None:
    """First candidate id that appears in *text* as its own token, or None.

    Boundaries are alphanumeric-only: a hyphen on either side never blocks a match, because
    this repo's own worktree-naming convention (``docs/plans/orbital-drift-alignment/
    PLAN.md`` Phase 0 §5) is ``worktree-<change-id>`` -- a hyphen-joined *prefix*, not a
    separate word -- and commit subjects commonly wrap an id the same way
    (``docs(add-panel-judge): ...``). What this still blocks is a direct alphanumeric
    extension (``lint`` must not match inside ``linter``). Candidates are checked
    longest-first so a more specific real id is preferred over a shorter one it happens to
    contain.
    """
    for change_id in sorted(candidate_ids, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(change_id)}(?![A-Za-z0-9])", text):
            return change_id
    return None


def infer_change_id(
    changes_root: Path,
    *,
    branch_name: str | None,
    recent_subjects: Sequence[str] = (),
) -> tuple[str | None, str | None]:
    """Guess a change id from *branch_name* first, then *recent_subjects*.

    Returns ``(change_id, source)`` where ``source`` is ``"branch"``, ``"commit"``, or (when
    nothing matched) ``(None, None)``. Candidates are the real directory names under
    ``changes_root`` — this never invents an id that doesn't exist on disk.
    """
    candidates = list_change_ids(changes_root)
    if not candidates:
        return None, None
    if branch_name:
        hit = _match_id_in_text(candidates, branch_name)
        if hit:
            return hit, "branch"
    for subject in recent_subjects:
        hit = _match_id_in_text(candidates, subject)
        if hit:
            return hit, "commit"
    return None, None


def _read_tasks_status(change_dir: Path) -> TaskStatus | None:
    tasks_path = change_dir / "tasks.md"
    if not tasks_path.is_file():
        return None
    return parse_tasks_status(tasks_path.read_text(encoding="utf-8"))


def locate_change(
    repo_root: Path,
    change_id: str | None = None,
    *,
    branch_name: str | None = None,
    recent_subjects: Sequence[str] | None = None,
) -> ChangeLocation:
    """Resolve *change_id* (or infer one) to a :class:`ChangeLocation`.

    When ``change_id`` is omitted, inference first tries ``branch_name`` (a real git call if
    not supplied) and falls back to ``recent_subjects`` (likewise). Raises
    :class:`ChangeNotFoundError` when an explicit id doesn't exist on disk, or when inference
    finds no candidate at all.
    """
    changes_root = repo_root / "openspec" / "changes"
    inferred = False
    inferred_from: str | None = None

    resolved_id = change_id
    if resolved_id is None:
        effective_branch = branch_name if branch_name is not None else current_branch_name(repo_root)
        effective_subjects = recent_subjects if recent_subjects is not None else recent_commit_subjects(repo_root)
        resolved_id, inferred_from = infer_change_id(
            changes_root, branch_name=effective_branch, recent_subjects=effective_subjects
        )
        inferred = True
        if resolved_id is None:
            raise ChangeNotFoundError(
                "no change id was given, and none could be inferred from the current branch "
                f"({effective_branch!r}) or the last {len(effective_subjects)} commit subject(s); "
                "pass --change explicitly"
            )

    change_dir = changes_root / resolved_id
    if not change_dir.is_dir():
        known = ", ".join(list_change_ids(changes_root)) or "(none found)"
        raise ChangeNotFoundError(f"no such change: {resolved_id!r} (looked in {change_dir}); known changes: {known}")

    review_path = change_dir / "review.md"
    return ChangeLocation(
        change_id=resolved_id,
        change_dir=change_dir,
        inferred=inferred,
        inferred_from=inferred_from,
        tasks_status=_read_tasks_status(change_dir),
        review_path=review_path,
        review_exists=review_path.is_file(),
    )
