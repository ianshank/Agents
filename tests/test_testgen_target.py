#!/usr/bin/env python3
"""Tests for the suite-execution target — the one place model-authored code runs.

Small inline focal methods rather than the committed corpus: every case here spends real
subprocesses (one per reference run plus one per mutant), so the fixtures are kept to one
or two mutants. ``tests/test_testgen_corpus.py`` covers the corpus itself.
"""

from __future__ import annotations

import socket
from pathlib import Path
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
        assert payload["green_on_correct"] == {"ran": 1, "failed": 0, "failures": {}}
        assert payload["mutants"] == {
            "generated": 1,
            "equivalent_excluded": 0,
            "covered": 1,
            "killed": 1,
            "errored": 0,
        }
        assert payload["mutant_errors"] == []
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
        assert payload["green_on_correct"]["ran"] == 1
        assert payload["green_on_correct"]["failed"] == 1
        assert payload["mutants"]["killed"] == 0, "a test already failing on correct code kills nothing"

    def test_a_false_alarm_carries_the_exception_that_caused_it(self) -> None:
        """`green_on_correct: 1/1 failed` is not a diagnosis; this is what makes it one.

        The first cut recorded only the failing test's NAME, so nothing the harness
        produced said why a suite was red against a known-correct implementation — the
        single most useful thing this capability can tell a reader.
        """
        always_red = "from focal import add\n\ndef test_wrong():\n    assert add(2, 1) == 999\n"
        failures = evidence_of(testgen.run_generated_suite(item(always_red)))["green_on_correct"]["failures"]
        assert set(failures) == {"test_wrong"}
        assert failures["test_wrong"].startswith("AssertionError")

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

    def test_each_run_gets_its_own_working_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The reference and each mutant must not see each other's `focal.py`.

        A leaked implementation would silently score one run against another's code — and
        because the reference runs first, every mutant would then look identical to it and
        nothing would ever be killed.

        Asserted against `_run_against`'s own layout choice, with `_execute` stubbed out:
        the property is where it writes, not what the subprocess then reports. The earlier
        version made two separate `run_generated_suite` calls and compared their kill
        counts, which is a property of the per-call `TemporaryDirectory` and holds however
        the subdirectories inside it are laid out — it passed with `workdir = root`, the
        exact regression it was named for, and spent four subprocesses to do it.
        """
        monkeypatch.setattr(testgen, "_execute", lambda workdir, timeout: ({}, None))
        labels = ("reference", "mutant-M1", "mutant-M2")
        for label in labels:
            testgen._run_against(tmp_path, label, f"# {label}\n" + FOCAL, FOCAL_NAME, KILLING_SUITE, 1.0)
        written = [
            path.read_text(encoding="utf-8") for path in sorted(tmp_path.rglob(testgen._suite_runner.FOCAL_FILENAME))
        ]
        assert len(written) == len(labels), "a run reused another run's sandbox directory"
        assert len(set(written)) == len(labels), "one sandbox overwrote another's focal module"

    def test_a_suites_network_use_never_reaches_the_harness_process(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Model-authored code runs OUT OF PROCESS, and this is what proves it.

        The earlier version of this test ran the harmless `KILLING_SUITE` and asserted the
        parent opened no socket. That could not fail: `run_generated_suite` touches no
        socket itself, and a monkeypatch in the parent is invisible to a subprocess, so the
        assertion held no matter what the suite did. It was named
        `test_execution_opens_no_socket` and its docstring claimed the offline property was
        "asserted directly" — false assurance on a security-relevant property.

        This version drives a suite that *does* attempt a connection. The parent's socket
        stays untouched precisely BECAUSE execution is out of process, so moving the runner
        in-process — the change this seam exists to forbid — turns the assertion red.

        What it does NOT claim: the sandbox itself is not network-isolated. A generated
        suite can still open sockets in its own interpreter. That gap is recorded in
        `docs/plans/eval-delivery-sequencing/PLAN.md` rather than papered over here.
        """
        connects: list[Any] = []
        real = socket.socket.connect

        def guarded(self: Any, address: Any) -> Any:
            connects.append(address)
            return real(self, address)

        monkeypatch.setattr(socket.socket, "connect", guarded)
        dialling = (
            "import socket\n"
            "from focal import add\n\n"
            "def test_dials_out():\n"
            "    s = socket.socket()\n"
            "    s.settimeout(0.05)\n"
            "    try:\n"
            "        s.connect(('127.0.0.1', 9))\n"
            "    except OSError:\n"
            "        pass\n"
            "    finally:\n"
            "        s.close()\n"
            "    assert add(2, 1) == -1\n"
        )
        payload = evidence_of(testgen.run_generated_suite(item(dialling)))
        # The suite really ran and really reached the fault -- without this the test could
        # pass by the suite never executing, which is how the previous version passed.
        assert payload["collected"] == 1
        assert payload["mutants"]["killed"] == 1
        assert connects == [], "a connect seen here means model-authored code ran in-process"

    def test_a_suite_that_prints_is_still_scored_correctly(self) -> None:
        """REGRESSION. A generated test calling `print()` is completely ordinary.

        The first cut of this target read the verdict from the runner's stdout, so any such
        suite corrupted the JSON and was scored NON-EXECUTABLE — a good suite failing for
        writing to a channel it had every right to write to, and one that would have
        systematically under-scored real model output. The verdict now travels through a
        file. Both the collection-time and the test-time print are covered, because they
        corrupt the stream at different points.
        """
        at_test_time = "from focal import add\n\ndef test_ok():\n    print('noisy')\n    assert add(2, 1) == -1\n"
        at_import_time = (
            "from focal import add\nprint('noisy at import')\n\ndef test_ok():\n    assert add(2, 1) == -1\n"
        )
        for suite in (at_test_time, at_import_time):
            result = testgen.run_generated_suite(item(suite))
            assert result.error is None, suite
            assert evidence_of(result)["collected"] == 1, suite

    def test_the_sandbox_stdout_is_not_buffered_into_the_harness(self) -> None:
        """A suite printing in a loop must not be accumulated in the harness's memory.

        `capture_output=True` would buffer it without bound; the sandbox's streams go to
        DEVNULL instead. Asserted by running a suite that emits ~4MB and observing a normal
        verdict rather than a memory-shaped failure.
        """
        loud = (
            "from focal import add\n\ndef test_loud():\n"
            "    for _ in range(4000):\n        print('x' * 1000)\n"
            "    assert add(2, 1) == -1\n"
        )
        result = testgen.run_generated_suite(item(loud))
        assert result.error is None
        assert evidence_of(result)["green_on_correct"]["ran"] == 1
        assert evidence_of(result)["green_on_correct"]["failed"] == 0

    def test_a_killed_mutant_is_always_counted_as_covered(self) -> None:
        """REGRESSION. `killed <= covered` is what keeps the normalized score inside [0, 1].

        This test previously asserted the opposite — that a mutant with no `differs_at`
        was killed but *not* covered — on the reasoning that crediting coverage the corpus
        had not declared would inflate the denominator. It deflates it: `killed=1,
        covered=0` is not a conservative reading, it is an arithmetically impossible one,
        and the normalized figure computed from it was `1/0`.

        A suite cannot make a mutant fail without driving an input at which the mutant
        differs. So a kill IS the coverage evidence, whatever the corpus declared, and
        counting it is a measurement rather than a concession.
        """
        unmarked = {key: value for key, value in MUTANT.items() if key != "differs_at"}
        payload = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE, mutants=[unmarked])))
        assert payload["mutants"]["killed"] == 1
        assert payload["mutants"]["covered"] == 1, "a kill is itself proof the suite reached the fault"

    def test_a_keyword_call_is_credited_as_coverage(self) -> None:
        """REGRESSION. `add(n=2, k=1)` and `add(2, 1)` must record the same grid point.

        The recorder logged raw `args`, so an entirely idiomatic keyword call looked like a
        call with no arguments: the mutant it reached was scored uncovered while still
        being killed. Verified end to end before the fix at a *normalized mutation score of
        2.0* — a rate above 1.0 flowing straight into a gate that takes the mean.

        The suite here reaches the fault by keyword and does NOT assert on it, so the
        mutant is covered but not killed. That separation is deliberate: a killing suite
        would be credited as covered by the kill rule above whether or not the recorder
        works, which makes a keyword *kill* useless as evidence about the recorder. This
        shape fails if the binding is removed; a killing one does not.
        """
        keyword_suite = "from focal import add\n\ndef test_smoke():\n    add(n=2, k=1)\n"
        payload = evidence_of(testgen.run_generated_suite(item(keyword_suite)))
        assert payload["mutants"]["killed"] == 0, "no assertion, so nothing detects the fault"
        assert payload["mutants"]["covered"] == 1, "the suite reached the differing input"

    def test_a_mutant_that_cannot_be_run_is_recorded_not_silently_dropped(self) -> None:
        """A mutant whose source will not import depresses both denominators.

        Before this the failure string was discarded at the loop and nothing anywhere
        distinguished "the suite missed this fault" from "the runner never got to try",
        which is exactly the infrastructure-failure-as-agent-failure collapse this
        package's docstring says it exists to prevent.
        """
        unrunnable = {**MUTANT, "id": "M-broken", "source": "def add(n, k):\n    (((\n"}
        payload = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE, mutants=[unrunnable])))
        assert payload["mutants"]["killed"] == 0
        assert payload["mutants"]["errored"] == 1
        assert [entry["id"] for entry in payload["mutant_errors"]] == ["M-broken"]
        assert payload["mutant_errors"][0]["reason"]

    def test_one_obligation_witnessed_twice_is_counted_once(self) -> None:
        """REGRESSION. Duplicate witnesses gave recall 2.0 with an empty `uncovered` list.

        Two obligation rows sharing an id and a witness mutant is a corpus-authoring slip,
        not a suite that covered twice as much as was asked of it.
        """
        duplicated = [{"id": "OB-1", "witness_mutant": "M1"}, {"id": "OB-1", "witness_mutant": "M1"}]
        payload = evidence_of(testgen.run_generated_suite(item(KILLING_SUITE, obligations=duplicated)))
        assert payload["obligations_covered"] == ["OB-1"]


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

    def test_a_runner_failure_is_distinguishable_from_a_suite_verdict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-zero runner exit, with no result file, must not read as "the suite failed"."""
        import subprocess

        def broken(*_a: Any, **_k: Any) -> Any:
            return subprocess.CompletedProcess([], returncode=3)

        monkeypatch.setattr(testgen.subprocess, "run", broken)
        result = testgen.run_generated_suite(item(KILLING_SUITE))
        assert result.error is not None and "runner exited 3" in result.error
        assert evidence_of(result)["collection_error"] == "reference run did not complete"

    def test_an_unparseable_result_file_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The verdict file exists but is not JSON — distinct from the runner never running."""
        import subprocess

        from eval_harness.targets import _suite_runner

        def corrupt(*args: Any, **kwargs: Any) -> Any:
            workdir = Path(kwargs["cwd"])
            (workdir / _suite_runner.RESULT_FILENAME).write_text("not json", encoding="utf-8")
            return subprocess.CompletedProcess([], returncode=0)

        monkeypatch.setattr(testgen.subprocess, "run", corrupt)
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

    def test_main_writes_the_verdict_to_a_file_not_stdout(self, tmp_path: Any) -> None:
        """The protocol must not share a channel with the code under test."""
        import json as _json

        from eval_harness.targets import _suite_runner

        (tmp_path / _suite_runner.FOCAL_FILENAME).write_text("x = 1\n", encoding="utf-8")
        (tmp_path / _suite_runner.SUITE_FILENAME).write_text("def test_x():\n    pass\n", encoding="utf-8")
        assert _suite_runner.main([str(tmp_path)]) == 0
        payload = _json.loads((tmp_path / _suite_runner.RESULT_FILENAME).read_text(encoding="utf-8"))
        assert payload["collected"] == 1

    def test_main_writes_a_traceback_file_and_exits_one_when_it_breaks(self, tmp_path: Any) -> None:
        """An absent focal module is the runner failing, not a suite verdict."""
        from eval_harness.targets import _suite_runner

        workdir = tmp_path / "empty"
        workdir.mkdir()
        assert _suite_runner.main([str(workdir)]) == 1
        assert not (workdir / _suite_runner.RESULT_FILENAME).exists()
        assert "Traceback" in (workdir / _suite_runner.RUNNER_ERROR_FILENAME).read_text(encoding="utf-8")
