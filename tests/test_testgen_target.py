#!/usr/bin/env python3
"""Tests for the suite-execution target — the one place model-authored code runs.

Small inline focal methods rather than the committed corpus: every case here spends real
subprocesses (one per reference run plus one per mutant), so the fixtures are kept to one
or two mutants. ``tests/test_testgen_corpus.py`` covers the corpus itself.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV, DisallowedImportError
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets import testgen

bootstrap()

#: A focal method with one branch, and the grid its mutant differs on.
FOCAL = "def add(n, k):\n    if n < 2:\n        return n + k\n    return k - n\n"
FOCAL_NAME = "add"

#: `n < 2` becomes `n <= 2`, which differs only at n == 2.
MUTANT = {
    "id": "M1",
    "kind": "relational",
    "equivalent": False,
    "source": "def add(n, k):\n    if n <= 2:\n        return n + k\n    return k - n\n",
    "differs_at": [1],
}

#: Grid index 0 is (0, 0) — where the mutant agrees; index 1 is (2, 1), where it differs.
GRID = [[0, 0], [2, 1]]


def item(suite: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "focal_name": FOCAL_NAME,
        "reference": FOCAL,
        "suite": suite,
        "mutants": [MUTANT],
        "obligations": [{"id": "OB-1", "witness_mutant": "M1"}],
        "grid": GRID,
    }
    payload.update(overrides)
    return payload


def evidence_of(result: Any) -> dict[str, Any]:
    payload = result.metadata[testgen.EVIDENCE_KEY]
    assert isinstance(payload, dict)
    return payload


#: A suite that drives the input where the mutant diverges, so it both covers and kills it.
KILLING_SUITE = "from focal import add\n\ndef test_boundary():\n    assert add(2, 1) == -1\n"

#: A suite that only drives an input where the mutant agrees: neither covered nor killed.
BLIND_SUITE = "from focal import add\n\ndef test_origin():\n    assert add(0, 0) == 0\n"


class TestSuiteExecution:
    def test_a_killing_suite_is_collected_covered_and_kills(self) -> None:
        result = testgen.run_generated_suite(item(KILLING_SUITE))
        payload = evidence_of(result)
        assert payload["collected"] == 1
        assert payload["collection_error"] is None
        assert payload["green_on_correct"] == {"ran": 1, "failed": 0}
        assert payload["mutants"] == {"generated": 1, "equivalent_excluded": 0, "covered": 1, "killed": 1}
        assert payload["obligations_covered"] == ["OB-1"]

    def test_a_blind_suite_is_neither_covered_nor_killed(self) -> None:
        """`covered` is measured from the inputs the suite actually drove, not assumed.

        This is what makes the normalized denominator meaningful: the suite runs green
        against reference and mutant alike, so it has not reached the fault at all.
        """
        payload = evidence_of(testgen.run_generated_suite(item(BLIND_SUITE)))
        assert payload["mutants"]["covered"] == 0
        assert payload["mutants"]["killed"] == 0
        assert payload["obligations_covered"] == []

    def test_a_suite_red_on_correct_code_cannot_claim_the_kill(self) -> None:
        """`killed` requires a test that PASSED on the reference to fail on the mutant.

        Without that rule a suite failing everywhere would score a perfect mutation kill
        rate, turning a false-alarm defect into evidence of fault detection.
        """
        always_red = "from focal import add\n\ndef test_wrong():\n    assert add(2, 1) == 999\n"
        payload = evidence_of(testgen.run_generated_suite(item(always_red)))
        assert payload["green_on_correct"] == {"ran": 1, "failed": 1}
        assert payload["mutants"]["killed"] == 0, "a test already failing on correct code kills nothing"

    def test_a_collection_error_is_evidence_not_an_exception(self) -> None:
        broken = "from focal import add\n\nraise RuntimeError('bad suite')\n"
        payload = evidence_of(testgen.run_generated_suite(item(broken)))
        assert payload["collected"] == 0
        assert payload["collection_error"] is not None and "RuntimeError" in payload["collection_error"]

    def test_a_suite_collecting_nothing_reports_zero_rather_than_omitting_it(self) -> None:
        payload = evidence_of(testgen.run_generated_suite(item("from focal import add\n")))
        assert payload["collected"] == 0
        assert payload["collection_error"] is None

    def test_equivalent_mutants_are_excluded_from_the_denominator(self) -> None:
        equivalent = dict(MUTANT, id="M2", equivalent=True)
        payload = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE, mutants=[MUTANT, equivalent])))
        assert payload["mutants"]["generated"] == 1
        assert payload["mutants"]["equivalent_excluded"] == 1


class TestBoundsAndFailureModes:
    def test_a_timeout_is_recorded_as_evidence_and_never_raised(self) -> None:
        """A raise here would abort the whole run under the default item-error policy."""
        hanging = "from focal import add\n\nwhile True:\n    pass\n"
        result = testgen.run_generated_suite(item(hanging, timeout_seconds=1.0))
        payload = evidence_of(result)
        assert payload["timed_out"] is True
        assert result.error == "timeout"

    def test_missing_inputs_are_reported_as_an_error_not_raised(self) -> None:
        result = testgen.run_generated_suite({"focal_name": FOCAL_NAME})
        assert result.error is not None and "missing" in result.error
        assert result.output is None

    def test_each_run_gets_its_own_working_directory(self) -> None:
        """Two runs must not see each other's files; a leaked `focal.py` would silently
        make the second run score the first run's implementation."""
        first = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE)))
        second = evidence_of(testgen.run_generated_suite(item(BLIND_SUITE)))
        assert first["mutants"]["killed"] == 1
        assert second["mutants"]["killed"] == 0

    def test_execution_opens_no_socket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The offline property is asserted directly, not inferred from `--offline`.

        `--offline` selects an in-memory Langfuse client; it is not a network kill-switch.
        The zero-dependency property has to come from the code, so it is checked here.
        """
        connects: list[Any] = []
        real = socket.socket.connect

        def guarded(self: Any, address: Any) -> Any:
            connects.append(address)
            return real(self, address)

        monkeypatch.setattr(socket.socket, "connect", guarded)
        testgen.run_generated_suite(item(KILLING_SUITE))
        assert connects == []

    def test_a_mutant_without_differs_at_is_not_counted_as_covered(self) -> None:
        """A corpus that does not publish differing indices cannot support the normalized
        denominator; counting the mutant anyway would inflate it silently."""
        unmarked = {key: value for key, value in MUTANT.items() if key != "differs_at"}
        payload = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE, mutants=[unmarked])))
        assert payload["mutants"]["covered"] == 0
        assert payload["mutants"]["killed"] == 1, "it can still be killed; it just cannot be credited as covered"


class TestAllowlist:
    """ADR 0039: executing model-authored code is gated, and the gate runs first."""

    def test_an_unlisted_target_is_refused_before_any_generated_code_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "something_else")
        target = TARGETS.create("callable", {"path": "eval_harness.targets.testgen:run_generated_suite"})
        from eval_harness.core.types import EvalItem

        with pytest.raises(DisallowedImportError, match=CALLABLE_ALLOWLIST_ENV):
            target.run(EvalItem(id="x", inputs=item(KILLING_SUITE), expected=None))

    def test_the_listed_target_resolves_and_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "eval_harness.targets.testgen")
        target = TARGETS.create("callable", {"path": "eval_harness.targets.testgen:run_generated_suite"})
        from eval_harness.core.types import EvalItem

        result = target.run(EvalItem(id="x", inputs=item(KILLING_SUITE), expected=None))
        assert evidence_of(result)["mutants"]["killed"] == 1


class TestRunnerProtocol:
    """The subprocess protocol, exercised through the runner module directly."""

    def test_the_runner_rejects_a_wrong_argument_count(self) -> None:
        from eval_harness.targets import _suite_runner

        assert _suite_runner.main([]) == 2

    def test_a_runner_failure_is_distinguishable_from_a_suite_verdict(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """A non-zero runner exit must not be read as "the suite failed"."""
        import subprocess

        def broken(*_a: Any, **_k: Any) -> Any:
            return subprocess.CompletedProcess([], returncode=3, stdout="", stderr="runner blew up")

        monkeypatch.setattr(testgen.subprocess, "run", broken)
        result = testgen.run_generated_suite(item(KILLING_SUITE))
        assert result.error is not None and "runner exited 3" in result.error
        assert evidence_of(result)["collection_error"] == "reference run did not complete"

    def test_unparseable_runner_output_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def noisy(*_a: Any, **_k: Any) -> Any:
            return subprocess.CompletedProcess([], returncode=0, stdout="not json", stderr="")

        monkeypatch.setattr(testgen.subprocess, "run", noisy)
        result = testgen.run_generated_suite(item(KILLING_SUITE))
        assert result.error is not None and "unparseable" in result.error


class TestSuiteRunnerInProcess:
    """The runner, called directly.

    It normally executes in a subprocess, where the parent's coverage cannot see it — so
    its branches are exercised here in-process. Not a duplicate of the target tests above:
    those prove the protocol works across the process boundary, these prove the runner's
    own collection and verdict logic, including the paths a healthy corpus never reaches.
    """

    @staticmethod
    def _sandbox(tmp_path: Any, focal: str, suite: str) -> Any:
        from eval_harness.targets import _suite_runner

        (tmp_path / _suite_runner.FOCAL_FILENAME).write_text(focal, encoding="utf-8")
        (tmp_path / _suite_runner.SUITE_FILENAME).write_text(suite, encoding="utf-8")
        return _suite_runner._report(tmp_path)

    def test_collects_test_prefixed_callables_in_name_order(self, tmp_path: Any) -> None:
        suite = "def test_b():\n    pass\n\ndef test_a():\n    pass\n\ndef helper():\n    raise AssertionError\n"
        payload = self._sandbox(tmp_path, "x = 1\n", suite)
        assert payload["collected"] == 2, "`helper` is not a test and must not be collected"
        assert payload["passed"] == ["test_a", "test_b"], "sorted, so the report is stable"

    def test_separates_passing_from_failing_tests(self, tmp_path: Any) -> None:
        suite = "def test_ok():\n    pass\n\ndef test_bad():\n    assert False\n"
        payload = self._sandbox(tmp_path, "x = 1\n", suite)
        assert payload["passed"] == ["test_ok"] and payload["failed"] == ["test_bad"]

    def test_a_test_raising_systemexit_is_a_failure_not_an_exit(self, tmp_path: Any) -> None:
        """`BaseException`, not `Exception`: a generated test can raise anything at all,
        and a bare `SystemExit` escaping the loop would end the runner mid-collection."""
        suite = "def test_exits():\n    raise SystemExit(3)\n"
        payload = self._sandbox(tmp_path, "x = 1\n", suite)
        assert payload["failed"] == ["test_exits"]

    def test_reports_recorded_calls_from_the_instrumented_focal_module(self, tmp_path: Any) -> None:
        focal = "__calls__ = [[[2, 1], {}]]\n"
        payload = self._sandbox(tmp_path, focal, "def test_x():\n    pass\n")
        assert payload["calls"] == [[[2, 1], {}]]

    def test_a_focal_module_without_the_recorder_reports_no_calls(self, tmp_path: Any) -> None:
        payload = self._sandbox(tmp_path, "x = 1\n", "def test_x():\n    pass\n")
        assert payload["calls"] == []

    def test_a_collection_failure_still_reports_the_calls_made_before_it(self, tmp_path: Any) -> None:
        focal = "__calls__ = [[[0, 0], {}]]\n"
        payload = self._sandbox(tmp_path, focal, "raise ValueError('nope')\n")
        assert payload["collected"] == 0
        assert payload["collection_error"] is not None and "ValueError" in payload["collection_error"]
        assert payload["calls"] == [[[0, 0], {}]]

    def test_main_writes_json_to_stdout_and_exits_zero(self, tmp_path: Any, capsys: Any) -> None:
        import json as _json

        from eval_harness.targets import _suite_runner

        (tmp_path / _suite_runner.FOCAL_FILENAME).write_text("x = 1\n", encoding="utf-8")
        (tmp_path / _suite_runner.SUITE_FILENAME).write_text("def test_x():\n    pass\n", encoding="utf-8")
        assert _suite_runner.main([str(tmp_path)]) == 0
        assert _json.loads(capsys.readouterr().out)["collected"] == 1

    def test_main_reports_a_runner_failure_as_exit_one(self, tmp_path: Any) -> None:
        """An absent focal module is the runner failing, not a suite verdict."""
        from eval_harness.targets import _suite_runner

        assert _suite_runner.main([str(tmp_path / "empty")]) == 1
