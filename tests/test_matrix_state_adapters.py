"""Test Matrix: the ``in_memory`` state adapter (F-060, ``add-stateful-outcome-evaluation``).

Split into its own file rather than grown inside ``test_matrix_eval_tools.py`` —
the cell-map extractor globs ``test_matrix_*.py``, so a per-feature file is a
first-class citizen (precedent: ``test_matrix_panel_judge.py``). ``state_adapter``'s
``REQUIRED_DIMS`` floor is ``{1, 2, 3, 5, 6}`` — the full set, unlike ``judge``'s
M5 exclusion — because every adapter shipped here is deterministic by design
(``design.md`` "Adapter scope"), not a provider-owned property (ADR 0032 errata,
2026-08-21).

Run: pytest tests/test_matrix_state_adapters.py -v --tb=short
"""

from __future__ import annotations

import pytest

from eval_harness.core.types import EvalItem, RunContext, StateEvaluation, StateSnapshot
from eval_harness.plugins import STATE_ADAPTERS, bootstrap

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
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"balance": 0}})
        before = adapter.snapshot(_CTX)
        adapter.set("balance", 100)
        after = adapter.snapshot(_CTX)
        ev = adapter.evaluate(item=_item(state_expectation={"balance": 100}), before=before, after=after)
        assert ev.goal_reached is True
        assert ev.policy_violated is False

    def test_m1_correctness_goal_not_reached_when_expectation_unmet(self) -> None:
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"balance": 0}})
        before = adapter.snapshot(_CTX)
        after = adapter.snapshot(_CTX)  # nothing written
        ev = adapter.evaluate(item=_item(state_expectation={"balance": 100}), before=before, after=after)
        assert ev.goal_reached is False

    def test_m1_correctness_goal_reached_via_forbidden_mutation_still_flags_policy(self) -> None:
        """The exact scenario tasks.md names: goal true, policy check failed, overall fail."""
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"balance": 0, "audit_log": "clean"}})
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
        adapter = STATE_ADAPTERS.create("in_memory")
        before = adapter.snapshot(_CTX)
        after = adapter.snapshot(_CTX)
        assert adapter.evaluate(item=_item(), before=before, after=after).goal_reached is False
        adapter.set("k", "v")
        assert adapter.evaluate(item=_item(), before=before, after=adapter.snapshot(_CTX)).goal_reached is True

    def test_m2_edge_no_forbidden_keys_declared_never_flags_policy(self) -> None:
        adapter = STATE_ADAPTERS.create("in_memory")
        before = adapter.snapshot(_CTX)
        adapter.set("anything", "changed")
        after = adapter.snapshot(_CTX)
        assert adapter.evaluate(item=_item(), before=before, after=after).policy_violated is False

    def test_m2_edge_reset_restores_the_initial_store_not_an_empty_one(self) -> None:
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"seed_key": "seed_value"}})
        adapter.set("scratch", "temp")
        adapter.reset(_CTX)
        assert adapter.snapshot(_CTX).data == {"seed_key": "seed_value"}

    # -------------------------------------------------------------- M3: type safety

    def test_m3_type_safety(self) -> None:
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"k": 1}})
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
        adapter = STATE_ADAPTERS.create("in_memory", {"initial": {"balance": 0}})
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
        adapter = STATE_ADAPTERS.create("in_memory")
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_expectation must be a mapping"):
            adapter.evaluate(item=_item(state_expectation=["not", "a", "mapping"]), before=snap, after=snap)

    def test_m6_error_non_iterable_forbidden_keys_rejected(self) -> None:
        adapter = STATE_ADAPTERS.create("in_memory")
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys=42), before=snap, after=snap)

    def test_m6_error_a_bare_string_forbidden_keys_is_rejected_not_iterated_as_chars(self) -> None:
        """A str is technically Iterable[str] -- guarding against the common footgun of
        one key ``"audit_log"`` silently being treated as ['a', 'u', 'd', 'i', 't', ...]."""
        adapter = STATE_ADAPTERS.create("in_memory")
        snap = adapter.snapshot(_CTX)
        with pytest.raises(TypeError, match="state_forbidden_keys must be an iterable"):
            adapter.evaluate(item=_item(state_forbidden_keys="audit_log"), before=snap, after=snap)
