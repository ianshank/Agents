"""Tests for `scripts/smokes/_smoke_lib.py` and the cross-language skip-code contract.

`scripts/smokes/` holds the Tier-D live-integration smokes. They are exercised here rather
than left to a live run because almost none of their logic is actually network-dependent:
env gating, exit-code selection, URL parsing and the trust-store fallback are all pure or
trivially fakeable, and each of them has already been a source of a false green.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts" / "smokes"))

import _smoke_lib as lib

ROOT = Path(__file__).resolve().parent.parent


class TestExitCodes:
    def test_skip_code_is_ex_config_not_two(self) -> None:
        """2 is what a missing file and an argparse error both produce, so it cannot mean
        'not configured' as well -- that ambiguity is what let Tier D report SKIP for
        steps that could never run."""
        assert lib.SKIP_EXIT_CODE == 78
        assert lib.SKIP_EXIT_CODE != 2

    def test_ok_and_fail_codes_are_distinct_and_conventional(self) -> None:
        assert lib.OK_EXIT_CODE == 0
        assert lib.FAIL_EXIT_CODE == 1
        assert len({lib.OK_EXIT_CODE, lib.FAIL_EXIT_CODE, lib.SKIP_EXIT_CODE}) == 3

    def test_powershell_runner_mirrors_the_python_skip_code(self) -> None:
        """Drift guard across the language boundary.

        The runner cannot import a Python constant, so it carries a literal. Nothing else
        would notice if one side were edited alone -- and the SKIP/FAIL distinction this
        branch exists to fix would silently regress. Same posture as
        `check_skill_script_drift.py`, which asserts vendored copies stay byte-identical.
        """
        runner = (ROOT / "scripts" / "run_all_e2e.ps1").read_text(encoding="utf-8")
        match = re.search(r"^\$SkipExitCode\s*=\s*(\d+)\s*$", runner, re.MULTILINE)
        assert match is not None, "run_all_e2e.ps1 no longer defines $SkipExitCode"
        assert int(match.group(1)) == lib.SKIP_EXIT_CODE

    def test_runner_does_not_reuse_two_as_a_skip_code(self) -> None:
        """The original bug, asserted directly so it cannot come back."""
        runner = (ROOT / "scripts" / "run_all_e2e.ps1").read_text(encoding="utf-8")
        assert "@(2)" not in runner


class TestMissingEnv:
    def test_reports_unset_names_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMOKE_A", raising=False)
        monkeypatch.setenv("SMOKE_B", "set")
        monkeypatch.delenv("SMOKE_C", raising=False)
        assert lib.missing_env(("SMOKE_A", "SMOKE_B", "SMOKE_C")) == ["SMOKE_A", "SMOKE_C"]

    def test_empty_string_counts_as_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exported-but-blank variable is a misconfiguration, not a value."""
        monkeypatch.setenv("SMOKE_A", "")
        assert lib.missing_env(("SMOKE_A",)) == ["SMOKE_A"]

    def test_returns_empty_when_all_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMOKE_A", "x")
        assert lib.missing_env(("SMOKE_A",)) == []


class TestTrustStore:
    def test_injects_and_reports_true_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        fake = types.ModuleType("truststore")
        fake.inject_into_ssl = lambda: calls.append(1)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "truststore", fake)

        assert lib.use_os_trust_store() is True
        assert calls == [1], "inject_into_ssl must actually be called, not merely importable"

    def test_reports_false_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`sys.modules[...] = None` forces ImportError even though truststore is installed
        in this venv -- the repo's documented idiom for the SDK-absent path."""
        monkeypatch.setitem(sys.modules, "truststore", None)
        assert lib.use_os_trust_store() is False


class TestScriptEntryPoints:
    """Run the smokes exactly as `run_all_e2e.ps1` does: `python <path>`, no package
    context, no pre-seeded sys.path.

    In-process tests import the modules with `scripts/smokes` already on `sys.path`, which
    bypasses their bootstrap entirely -- so without these, the one code path the runner
    actually uses is the one path never exercised. They also pin the exit-code contract at
    the process boundary, which is where the runner reads it.
    """

    @pytest.mark.parametrize("script", ["langfuse_smoke.py", "phoenix_smoke.py"])
    def test_exits_with_skip_code_when_unconfigured(self, script: str) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGFUSE_", "PHOENIX_"))}
        # Keep PATH/SystemRoot etc.; only the integration's own variables are stripped.
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smokes" / script)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert result.returncode == lib.SKIP_EXIT_CODE, (
            f"{script} exited {result.returncode}, expected {lib.SKIP_EXIT_CODE}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "SKIP" in result.stdout

    @pytest.mark.parametrize("script", ["langfuse_smoke.py", "phoenix_smoke.py"])
    def test_never_exits_two_when_unconfigured(self, script: str) -> None:
        """2 is reserved for 'the script itself is broken' (missing file, bad flag). If a
        smoke ever returns it for a missing credential, the runner cannot tell the two
        apart -- which is the exact defect this branch fixed."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGFUSE_", "PHOENIX_"))}
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "smokes" / script)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        assert result.returncode != 2


class TestRedaction:
    """Exception text is untrusted data, not a trusted string.

    An SDK, a proxy, or a URL carrying userinfo can echo a credential back inside the
    message it raises, and these lines land in `artifacts/e2e-report/*.log`, which gets
    copied around and quoted into PRs. gitleaks is CI-only and never reads those logs, so
    redaction has to live in the formatter rather than in human discipline.
    """

    def test_replaces_every_secret_occurrence(self) -> None:
        out = lib.redact("key=abc123 retry with abc123", ["abc123"])
        assert "abc123" not in out
        assert out.count(lib.REDACTION) == 2

    def test_ignores_empty_and_blank_secrets(self) -> None:
        """An unset credential is an empty string; substituting it would redact every
        character boundary in the message and destroy the diagnostic."""
        assert lib.redact("nothing secret here", ["", "   ", None or ""]) == "nothing secret here"

    def test_no_secrets_is_a_passthrough(self) -> None:
        assert lib.redact("plain", None) == "plain"
        assert lib.redact("plain", []) == "plain"

    def test_format_failure_redacts_a_secret_inside_the_exception(self) -> None:
        out = lib.format_failure("x", RuntimeError("rejected token sk-live-123"), secrets=["sk-live-123"])
        assert "sk-live-123" not in out
        assert lib.REDACTION in out
        assert "RuntimeError" in out, "the exception type must survive redaction"


class TestSafeEndpoint:
    def test_strips_userinfo_path_and_query(self) -> None:
        out = lib.safe_endpoint("https://user:pa55w0rd@host.example:8443/v1/traces?token=abc")
        assert out == "https://host.example:8443"
        assert "pa55w0rd" not in out
        assert "abc" not in out

    def test_keeps_scheme_and_host_when_no_port(self) -> None:
        assert lib.safe_endpoint("https://host.example") == "https://host.example"

    def test_unparseable_url_redacts_entirely(self) -> None:
        """Better to say nothing than to echo something we could not parse."""
        assert lib.safe_endpoint("not-a-url") == lib.REDACTION


class TestFormatters:
    def test_format_missing_names_every_variable(self) -> None:
        out = lib.format_missing("x-smoke", ["A", "B"])
        assert out == "x-smoke: SKIP, unset: A, B"

    def test_format_failure_carries_type_and_message(self) -> None:
        out = lib.format_failure("x-smoke", ValueError("boom"))
        assert "ValueError" in out and "boom" in out and "FAIL" in out

    def test_format_failure_appends_hint_when_given(self) -> None:
        assert lib.format_failure("x", ValueError("b"), " -- do the thing").endswith(" -- do the thing")

    def test_format_failure_omits_hint_by_default(self) -> None:
        assert lib.format_failure("x", ValueError("b")).endswith("boom") is False
        assert lib.format_failure("x", ValueError("b")) == "x: FAIL, ValueError: b"
