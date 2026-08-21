"""Test Matrix: the ``in_memory``/``filesystem``/``sqlite`` state adapters
(F-060, ``add-stateful-outcome-evaluation``).

Split into its own file rather than grown inside ``test_matrix_eval_tools.py`` —
the cell-map extractor globs ``test_matrix_*.py``, so a per-feature file is a
first-class citizen (precedent: ``test_matrix_panel_judge.py``). ``state_adapter``'s
``REQUIRED_DIMS`` floor is ``{1, 2, 3, 5, 6}`` — the full set, unlike ``judge``'s
M5 exclusion — because every adapter shipped here is deterministic by design
(``design.md`` "Adapter scope"), not a provider-owned property (ADR 0032 errata,
2026-08-21).

Adapters are constructed directly (``InMemoryStateAdapter(...)``, not
``STATE_ADAPTERS.create("in_memory", ...)``) — these tests exercise each
adapter's own extended surface (``set``/``update``, ``root``) beyond the
``StateAdapter`` Protocol, which the registry's ``create()`` cannot statically
type. Registry wiring itself is proven separately
(``tests/test_state_adapter_contracts.py``, ``tests/test_state_lifecycle.py``'s
``TestConfigWiring``); ``bootstrap()`` here only keeps ``STATE_ADAPTERS``
populated for the census cross-check ``tests/_matrix_coverage.py`` runs
against ``MATRIX_COMPONENTS`` in a separate process.

Run: pytest tests/test_matrix_state_adapters.py -v --tb=short
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from eval_harness.core.types import EvalItem, RunContext, StateEvaluation, StateSnapshot
from eval_harness.plugins import bootstrap
from eval_harness.state_adapters import FilesystemStateAdapter, InMemoryStateAdapter, SqliteStateAdapter

_ACCOUNTS_SCHEMA = "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, balance INTEGER);"
_ACCOUNTS_SEED = "INSERT INTO accounts VALUES (1, 'alice', 100), (2, 'bob', 50);"

bootstrap()

_CTX = RunContext(config=None)


def _item(item_id: str = "i1", **metadata: object) -> EvalItem:
    return EvalItem(id=item_id, inputs={}, expected=None, metadata=dict(metadata))


class TestInMemoryStateAdapter:
    """``in_memory`` state adapter test matrix."""

    MATRIX_KIND = "state_adapter"
    MATRIX_COMPONENTS = ("in_memory",)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_goal_reached_when_expectation_met(self) -> None:
        adapter = InMemoryStateAdapter(initial={"balance": 0})
        before = adapter.snapshot(_CTX)
        adapter.set("balance", 100)
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(item=_item(state_expectation={"balance": 100}), before=before, after=after)
        assert ev.goal_reached is True
        assert ev.policy_violated is False

    def test_m1_correctness_goal_not_reached_when_expectation_unmet(self) -> None:
        adapter = InMemoryStateAdapter(initial={"balance": 0})
        before = adapter.snapshot(_CTX)
        after = adapter.snapshot(_CTX)  # nothing written
        ev = adapter.evaluate(item=_item(state_expectation={"balance": 100}), before=before, after=after)
        assert ev.goal_reached is False

    def test_m1_correctness_goal_reached_via_forbidden_mutation_still_flags_policy(self) -> None:
        """The exact scenario tasks.md names: goal true, policy check failed, overall fail."""
        adapter = InMemoryStateAdapter(initial={"balance": 0, "audit_log": "clean"})
        before = adapter.snapshot(_CTX)
        adapter.set("balance", 100)
        adapter.set("audit_log", "tampered")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(
            item=_item(state_expectation={"balance": 100}, state_forbidden_keys=["audit_log"]),
            before=before,
            after=after,
        )
        assert ev.goal_reached is True
        assert ev.policy_violated is True

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_no_expectation_declared_reports_whether_anything_changed(self) -> None:
        adapter = InMemoryStateAdapter()
        before = adapter.snapshot(_CTX)
        after = adapter.snapshot(_CTX)
        assert adapter.evaluate(item=_item(), before=before, after=after).goal_reached is False
        adapter.set("k", "v")
        assert adapter.evaluate(item=_item(), before=before, after=adapter.snapshot(_CTX)).goal_reached is True

    def test_m2_edge_no_forbidden_keys_declared_never_flags_policy(self) -> None:
        adapter = InMemoryStateAdapter()
        before = adapter.snapshot(_CTX)
        adapter.set("anything", "changed")
        after = adapter.snapshot(_CTX)
        assert adapter.evaluate(item=_item(), before=before, after=after).policy_violated is False

    def test_m2_edge_reset_restores_the_initial_store_not_an_empty_one(self) -> None:
        adapter = InMemoryStateAdapter(initial={"seed_key": "seed_value"})
        adapter.set("scratch", "temp")
        adapter.reset(_CTX)
        assert adapter.snapshot(_CTX).data == {"seed_key": "seed_value"}

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        adapter = InMemoryStateAdapter(initial={"k": 1})
        snap = adapter.snapshot(_CTX)
        assert isinstance(snap, StateSnapshot)
        with pytest.raises(TypeError):
            snap.data["k"] = 2  # type: ignore[index]
        ev = adapter.evaluate(item=_item(), before=snap, after=snap)
        assert isinstance(ev, StateEvaluation)
        assert isinstance(ev.goal_reached, bool)
        assert isinstance(ev.policy_violated, bool)
        assert isinstance(ev.reasoning, str)

    # -------------------------------------------------------------- M5: determinism

    def test_m5_determinism(self) -> None:
        adapter = InMemoryStateAdapter(initial={"balance": 0})
        before = adapter.snapshot(_CTX)
        adapter.set("balance", 100)
        after = adapter.snapshot(_CTX)
        item = _item(state_expectation={"balance": 100}, state_forbidden_keys=["audit_log"])
        results = [adapter.evaluate(item=item, before=before, after=after) for _ in range(10)]
        assert all(r.goal_reached == results[0].goal_reached for r in results)
        assert all(r.policy_violated == results[0].policy_violated for r in results)
        assert all(r.reasoning == results[0].reasoning for r in results)

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_non_mapping_state_expectation_rejected(self) -> None:
        adapter = InMemoryStateAdapter()
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_expectation must be a mapping"):
            adapter.evaluate(item=_item(state_expectation=["not", "a", "mapping"]), before=snap, after=snap)

    def test_m6_error_non_iterable_forbidden_keys_rejected(self) -> None:
        adapter = InMemoryStateAdapter()
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys=42), before=snap, after=snap)

    def test_m6_error_a_bare_string_forbidden_keys_is_rejected_not_iterated_as_chars(self) -> None:
        """A str is technically Iterable[str] -- guarding against the common footgun of
        one key ``"audit_log"`` silently being treated as ['a', 'u', 'd', 'i', 't', ...]."""
        adapter = InMemoryStateAdapter()
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys="audit_log"), before=snap, after=snap)


class TestFilesystemStateAdapter:
    """``filesystem`` state adapter test matrix."""

    MATRIX_KIND = "state_adapter"
    MATRIX_COMPONENTS = ("filesystem",)

    def _write(self, adapter: FilesystemStateAdapter, relative_path: str, content: str) -> None:
        path = adapter.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_goal_reached_when_file_content_matches(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        before = adapter.snapshot(_CTX)
        self._write(adapter, "output.txt", "hello world")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(item=_item(state_expectation={"output.txt": "hello world"}), before=before, after=after)
        assert ev.goal_reached is True

    def test_m1_correctness_goal_not_reached_on_content_mismatch(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        before = adapter.snapshot(_CTX)
        self._write(adapter, "output.txt", "wrong content")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(item=_item(state_expectation={"output.txt": "hello world"}), before=before, after=after)
        assert ev.goal_reached is False

    def test_m1_correctness_goal_reached_via_forbidden_write_still_flags_policy(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        self._write(adapter, "audit.log", "clean")
        before = adapter.snapshot(_CTX)
        self._write(adapter, "output.txt", "hello world")
        self._write(adapter, "audit.log", "tampered")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(
            item=_item(state_expectation={"output.txt": "hello world"}, state_forbidden_keys=["audit.log"]),
            before=before,
            after=after,
        )
        assert ev.goal_reached is True
        assert ev.policy_violated is True

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_default_root_is_a_fresh_unique_temp_directory(self) -> None:
        a1 = FilesystemStateAdapter()
        a2 = FilesystemStateAdapter()
        assert a1.root != a2.root
        assert a1.root.is_dir()

    def test_m2_edge_empty_sandbox_snapshots_as_an_empty_mapping(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        assert adapter.snapshot(_CTX).data == {}

    def test_m2_edge_reset_removes_files_written_during_the_attempt(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        self._write(adapter, "scratch.txt", "temp")
        adapter.reset(_CTX)
        assert adapter.snapshot(_CTX).data == {}
        assert adapter.root.is_dir()  # the root itself survives reset, just emptied

    def test_m2_edge_nested_directories_are_hashed_by_their_full_relative_path(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        self._write(adapter, "a/b/c.txt", "nested")
        assert list(adapter.snapshot(_CTX).data) == ["a/b/c.txt"]

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        snap = adapter.snapshot(_CTX)
        assert isinstance(snap, StateSnapshot)
        assert isinstance(snap.data, Mapping)
        ev = adapter.evaluate(item=_item(), before=snap, after=snap)
        assert isinstance(ev, StateEvaluation)
        assert isinstance(ev.goal_reached, bool)

    # -------------------------------------------------------------- M5: determinism

    def test_m5_determinism(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        self._write(adapter, "output.txt", "hello world")
        snap = adapter.snapshot(_CTX)
        results = [snap.data for _ in range(5)] + [adapter.snapshot(_CTX).data for _ in range(5)]
        assert all(r == results[0] for r in results)  # same content -> same hash, every time

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_non_mapping_state_expectation_rejected(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_expectation must be a mapping"):
            adapter.evaluate(item=_item(state_expectation=["not", "a", "mapping"]), before=snap, after=snap)

    def test_m6_error_non_iterable_forbidden_keys_rejected(self, tmp_path) -> None:
        adapter = FilesystemStateAdapter(root=str(tmp_path / "sandbox"))
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys=42), before=snap, after=snap)


class TestSqliteStateAdapter:
    """``sqlite`` state adapter test matrix."""

    MATRIX_KIND = "state_adapter"
    MATRIX_COMPONENTS = ("sqlite",)

    def _adapter(self) -> SqliteStateAdapter:
        return SqliteStateAdapter(schema_sql=_ACCOUNTS_SCHEMA, seed_sql=_ACCOUNTS_SEED)

    # -------------------------------------------------------------- M1: correctness

    def test_m1_correctness_goal_reached_when_expected_rows_match(self) -> None:
        adapter = self._adapter()
        before = adapter.snapshot(_CTX)
        adapter.conn.execute("UPDATE accounts SET balance = 999 WHERE id = 1")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(
            item=_item(state_expectation={"accounts": [(1, "alice", 999), (2, "bob", 50)]}),
            before=before,
            after=after,
        )
        assert ev.goal_reached is True

    def test_m1_correctness_goal_not_reached_on_mismatch(self) -> None:
        adapter = self._adapter()
        before = adapter.snapshot(_CTX)
        after = adapter.snapshot(_CTX)  # nothing changed
        ev = adapter.evaluate(
            item=_item(state_expectation={"accounts": [(1, "alice", 999), (2, "bob", 50)]}),
            before=before,
            after=after,
        )
        assert ev.goal_reached is False

    def test_m1_correctness_goal_reached_via_forbidden_table_mutation_still_flags_policy(self) -> None:
        """The exact scenario tasks.md names: goal true, policy check failed, overall fail."""
        adapter = SqliteStateAdapter(
            schema_sql=_ACCOUNTS_SCHEMA + " CREATE TABLE audit_log (id INTEGER PRIMARY KEY, note TEXT);",
            seed_sql=_ACCOUNTS_SEED + " INSERT INTO audit_log VALUES (1, 'clean');",
        )
        before = adapter.snapshot(_CTX)
        adapter.conn.execute("UPDATE accounts SET balance = 999 WHERE id = 1")
        adapter.conn.execute("UPDATE audit_log SET note = 'tampered' WHERE id = 1")
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(
            item=_item(
                state_expectation={"accounts": [(1, "alice", 999), (2, "bob", 50)]},
                state_forbidden_keys=["audit_log"],
            ),
            before=before,
            after=after,
        )
        assert ev.goal_reached is True
        assert ev.policy_violated is True

    # -------------------------------------------------------------- M2: edge cases

    def test_m2_edge_default_db_path_is_isolated_per_instance(self) -> None:
        a1 = self._adapter()
        a2 = self._adapter()
        a1.conn.execute("UPDATE accounts SET balance = 1 WHERE id = 1")
        assert a1.snapshot(_CTX).data != a2.snapshot(_CTX).data

    def test_m2_edge_no_tables_snapshots_as_an_empty_mapping(self) -> None:
        adapter = SqliteStateAdapter()
        assert adapter.snapshot(_CTX).data == {}

    def test_m2_edge_reset_rolls_back_across_multiple_attempts(self) -> None:
        adapter = self._adapter()
        seeded = adapter.snapshot(_CTX).data
        adapter.conn.execute("UPDATE accounts SET balance = 1 WHERE id = 1")
        adapter.reset(_CTX)
        assert adapter.snapshot(_CTX).data == seeded
        adapter.conn.execute("UPDATE accounts SET balance = 2 WHERE id = 2")  # a second attempt
        adapter.reset(_CTX)
        assert adapter.snapshot(_CTX).data == seeded

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        adapter = self._adapter()
        snap = adapter.snapshot(_CTX)
        assert isinstance(snap, StateSnapshot)
        assert isinstance(snap.data, Mapping)
        assert isinstance(snap.data["accounts"], tuple)
        ev = adapter.evaluate(item=_item(), before=snap, after=snap)
        assert isinstance(ev, StateEvaluation)
        assert isinstance(ev.goal_reached, bool)

    # -------------------------------------------------------------- M5: determinism

    def test_m5_determinism(self) -> None:
        adapter = self._adapter()
        results = [adapter.snapshot(_CTX).data for _ in range(10)]
        assert all(r == results[0] for r in results)

    # -------------------------------------------------------------- M6: error handling

    def test_m6_error_non_mapping_state_expectation_rejected(self) -> None:
        adapter = self._adapter()
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_expectation must be a mapping"):
            adapter.evaluate(item=_item(state_expectation=["not", "a", "mapping"]), before=snap, after=snap)

    def test_m6_error_non_iterable_forbidden_keys_rejected(self) -> None:
        adapter = self._adapter()
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys=42), before=snap, after=snap)
