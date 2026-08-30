"""Tests for run_pre_pr_gate.py: the make-pre-pr subprocess wrapper.

Exercises the real fixture Makefiles under evals/fixtures/ for the ordinary
success/failure/missing-Makefile paths (fast -- their `pre-pr` targets are a single
echo, no real check battery runs), and mocks subprocess.run for the timeout and
executable-not-found paths, which the fixtures cannot trigger deterministically.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import run_pre_pr_gate as gate

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "fixtures"


class TestAsText:
    def test_none_becomes_empty_string(self) -> None:
        assert gate._as_text(None) == ""

    def test_str_passes_through_unchanged(self) -> None:
        assert gate._as_text("already text") == "already text"

    def test_bytes_are_decoded_as_utf8(self) -> None:
        assert gate._as_text("café".encode()) == "café"

    def test_invalid_utf8_bytes_are_replaced_not_raised(self) -> None:
        assert gate._as_text(b"\xff\xfe") == "��"


class TestRunGate:
    def test_passing_fixture_reports_success(self) -> None:
        passed, exit_code, output = gate.run_gate(FIXTURES / "passing", "pre-pr", None, timeout=30)
        assert passed is True
        assert exit_code == 0
        assert "fixture: all checks passed" in output

    def test_failing_fixture_reports_failure_and_relays_output(self) -> None:
        passed, exit_code, output = gate.run_gate(FIXTURES / "failing", "pre-pr", None, timeout=30)
        assert passed is False
        assert exit_code != 0  # make's own exit code on a failed recipe (2), not the recipe's raw `exit 1`
        assert "fixture: a check failed" in output

    def test_missing_makefile_fails_closed(self) -> None:
        passed, exit_code, _output = gate.run_gate(FIXTURES / "no-makefile", "pre-pr", None, timeout=30)
        assert passed is False
        assert exit_code != 0

    def test_base_ref_override_reaches_the_makefile(self) -> None:
        passed, _exit_code, output = gate.run_gate(FIXTURES / "passing", "pre-pr", "some/custom-ref", timeout=30)
        assert passed is True
        assert "base-ref=some/custom-ref" in output

    def test_base_ref_omitted_uses_the_makefiles_own_default(self) -> None:
        passed, _exit_code, output = gate.run_gate(FIXTURES / "passing", "pre-pr", None, timeout=30)
        assert passed is True
        assert "base-ref=origin/main" in output  # the fixture Makefile's own `?=` default

    def test_timeout_reports_failure_with_a_124_exit_code(self) -> None:
        with patch.object(
            gate.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["make", "pre-pr"], timeout=5, output="partial", stderr=""),
        ):
            passed, exit_code, output = gate.run_gate(FIXTURES / "passing", "pre-pr", None, timeout=5)
        assert passed is False
        assert exit_code == 124
        assert "timed out after 5s" in output
        assert "partial" in output  # partial output captured before the timeout is not discarded

    def test_make_not_found_fails_closed_with_a_127_exit_code(self) -> None:
        with patch.object(gate.subprocess, "run", side_effect=FileNotFoundError("make")):
            passed, exit_code, output = gate.run_gate(FIXTURES / "passing", "pre-pr", None, timeout=30)
        assert passed is False
        assert exit_code == 127
        assert "could not run" in output


class TestWriteReport:
    def test_writes_valid_json_with_the_expected_shape(self, tmp_path: Path) -> None:
        out = tmp_path / "report.json"
        gate.write_report(out, passed=True, exit_code=0, target="pre-pr", root=Path("/repo"))
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload == {"passed": True, "exit_code": 0, "target": "pre-pr", "root": "/repo"}

    def test_creates_missing_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deeper" / "report.json"
        gate.write_report(out, passed=False, exit_code=1, target="pre-pr", root=tmp_path)
        assert out.is_file()


class TestMain:
    def test_passing_run_exits_zero(self, capsys) -> None:
        rc = gate.main(["--root", str(FIXTURES / "passing")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "pre-pr-gate: OK" in out

    def test_failing_run_exits_nonzero_and_says_failed(self, capsys) -> None:
        rc = gate.main(["--root", str(FIXTURES / "failing")])
        assert rc != 0
        out = capsys.readouterr().out
        assert "pre-pr-gate: FAILED" in out

    def test_out_flag_writes_a_report_reflecting_the_result(self, tmp_path: Path) -> None:
        out_path = tmp_path / "report.json"
        rc = gate.main(["--root", str(FIXTURES / "failing"), "--out", str(out_path)])
        assert rc != 0
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["passed"] is False
        assert payload["exit_code"] == rc
        assert payload["target"] == gate.DEFAULT_TARGET

    def test_no_out_flag_does_not_write_anything(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        rc = gate.main(["--root", str(FIXTURES / "passing")])
        assert rc == 0
        assert list(tmp_path.iterdir()) == []  # nothing written under the cwd

    def test_custom_target_and_base_ref_are_honoured(self) -> None:
        rc = gate.main(
            ["--root", str(FIXTURES / "passing"), "--target", "pre-pr", "--base-ref", "abc123", "--timeout", "30"]
        )
        assert rc == 0
