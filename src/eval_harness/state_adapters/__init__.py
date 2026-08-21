"""Built-in state adapters.

Every adapter here is local and deterministic: in-memory mapping, filesystem
sandbox, SQLite transaction, in-process mock HTTP. The offline suite's
zero-external-dependency property holds — no production credentials and no
domain-specific adapters ship in this package; those arrive later behind the
same ``StateAdapter`` seam (``core/interfaces.py``).
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..core.interfaces import StateAdapter
from ..core.types import EvalItem, RunContext, StateEvaluation, StateSnapshot
from ..plugins import STATE_ADAPTERS
from ._common import evaluate_key_value_state


@STATE_ADAPTERS.register("in_memory")
class InMemoryStateAdapter(StateAdapter):
    """A mutable in-memory key/value store, reset to its initial state per attempt.

    The reference, simplest adapter: no I/O, fully deterministic. Whatever
    drives world-state changes during ``target.run(item)`` — typically the
    target itself, holding a reference to the same adapter instance — calls
    :meth:`set`/:meth:`update` directly; the adapter does not intercept or
    observe the target's execution, only what it is told.

    ``evaluate`` reads two optional, per-item conventions from
    ``item.metadata`` (mirrors ``TrajectoryStepEfficiencyScorer``'s
    ``step_budget`` convention — no new ``EvalItem`` field):

    * ``state_expectation``: a mapping of keys to their expected value after
      the attempt. ``goal_reached`` is true when every declared key matches.
      Absent entirely, ``goal_reached`` reports whether the store changed at
      all (a bare "did anything happen" signal).
    * ``state_forbidden_keys``: keys that must not change. ``policy_violated``
      is true when any of them did — independent of ``goal_reached``, so an
      attempt can reach its declared goal via a forbidden mutation.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._initial: dict[str, Any] = dict(initial or {})
        self._store: dict[str, Any] = dict(self._initial)

    def set(self, key: str, value: Any) -> None:
        """Write one key — the adapter's own mutation surface."""
        self._store[key] = value

    def update(self, values: Mapping[str, Any]) -> None:
        """Write several keys at once."""
        self._store.update(values)

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        return StateSnapshot(data=dict(self._store))

    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
        return evaluate_key_value_state(item, before, after)

    def reset(self, ctx: RunContext) -> None:
        self._store = dict(self._initial)


@STATE_ADAPTERS.register("filesystem")
class FilesystemStateAdapter(StateAdapter):
    """A sandboxed directory tree, reset to empty per attempt.

    ``root`` defaults to a fresh, unique temp directory. Confinement is
    achieved by exposing this single directory as the sandbox surface —
    whatever plays the role of the target's world writes under :attr:`root`
    — not by intercepting writes elsewhere; the same trust boundary
    :class:`InMemoryStateAdapter` has for its own ``set()``/``update()``.

    :meth:`snapshot` walks ``root`` recursively and hashes each file's
    content (sha256) rather than storing raw bytes, so a snapshot stays
    lightweight regardless of file size. ``evaluate`` reuses
    :func:`evaluate_key_value_state`'s ``state_expectation``/
    ``state_forbidden_keys`` conventions, with expected content hashed the
    same way before comparing — since the snapshot never stores raw content.
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="eval-harness-fs-state-"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _hash_tree(self) -> dict[str, Any]:
        return {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        }

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        return StateSnapshot(data=self._hash_tree())

    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
        return evaluate_key_value_state(
            item, before, after, expected_transform=lambda content: hashlib.sha256(content.encode()).hexdigest()
        )

    def reset(self, ctx: RunContext) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)


_SAVEPOINT = "eval_harness_seed"


@STATE_ADAPTERS.register("sqlite")
class SqliteStateAdapter(StateAdapter):
    """A SQLite database, reset to its seeded state per attempt via a real
    transaction rollback -- not a re-run of the seed SQL.

    ``schema_sql``/``seed_sql`` run once at construction; a
    ``SAVEPOINT`` is taken immediately after. :meth:`reset` issues
    ``ROLLBACK TO SAVEPOINT`` (undoing everything the previous attempt did,
    schema-level constructs like autoincrement sequences included) and
    re-establishes the savepoint for the next attempt. ``db_path`` defaults
    to ``:memory:`` — a fresh, isolated database per adapter instance.
    :attr:`conn` is the adapter's own mutation surface — whatever plays the
    role of the target's world executes SQL against it directly, mirroring
    :class:`InMemoryStateAdapter`'s ``set()``/``update()``.

    :meth:`snapshot` reads every table ``sqlite_master`` reports, each as
    ``SELECT * FROM <table> ORDER BY 1`` — ordering by the first column is a
    documented simplification (assumes a stable, comparable leading column;
    a reference adapter, not a general-purpose schema-aware differ) so two
    snapshots of unchanged data compare equal regardless of physical row
    order. ``evaluate`` reuses :func:`evaluate_key_value_state` at
    whole-table granularity: ``state_expectation``/``state_forbidden_keys``
    key by table name, values are the expected rows (lists/tuples of
    columns), transformed into the same row-tuple shape :meth:`snapshot`
    produces before comparing.
    """

    def __init__(self, schema_sql: str = "", seed_sql: str = "", db_path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.executescript(schema_sql)
        self.conn.executescript(seed_sql)
        self.conn.commit()
        self._tables = self._discover_tables()
        self.conn.execute(f"SAVEPOINT {_SAVEPOINT}")

    def _discover_tables(self) -> tuple[str, ...]:
        cursor = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return tuple(row[0] for row in cursor.fetchall())

    def _query_table(self, table: str) -> tuple[tuple[Any, ...], ...]:
        cursor = self.conn.execute(f"SELECT * FROM {table} ORDER BY 1")
        return tuple(tuple(row) for row in cursor.fetchall())

    def snapshot(self, ctx: RunContext) -> StateSnapshot:
        return StateSnapshot(data={table: self._query_table(table) for table in self._tables})

    def evaluate(self, *, item: EvalItem, before: StateSnapshot, after: StateSnapshot) -> StateEvaluation:
        return evaluate_key_value_state(
            item, before, after, expected_transform=lambda rows: tuple(tuple(r) for r in rows)
        )

    def reset(self, ctx: RunContext) -> None:
        self.conn.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
        self.conn.execute(f"SAVEPOINT {_SAVEPOINT}")
