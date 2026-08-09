"""Tests for `scripts/smokes/langfuse_smoke.py`.

The behaviour that matters here is that the smoke must FAIL when the backend rejects or
cannot be reached. An earlier version could not: `log_score`/`flush` route transport errors
to the SDK's own logger and return normally, so it printed OK and exited 0 while every call
was erroring. `auth_check()` is the only call that reports failure, and
`test_fails_when_auth_check_returns_false` / `..._raises` are the guards on that.

`test_no_credential_value_is_ever_printed` covers the module's stated privacy promise across
*every* reachable exit path, not just the happy one.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent / "scripts" / "smokes"))

import _smoke_lib as lib
import langfuse_smoke as ls

SECRET_SENTINEL = "do-not-print-secret-9f3ac2"
PUBLIC_SENTINEL = "do-not-print-public-4b71de"
BASE_URL = "https://langfuse.test"


@pytest.fixture
def creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET_SENTINEL)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC_SENTINEL)
    monkeypatch.setenv("LANGFUSE_BASE_URL", BASE_URL)


@pytest.fixture
def fake_langfuse(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake `langfuse` module.

    `main()` constructs `Langfuse()` with no args and `SDKLangfuseClient` constructs
    `Langfuse(**kwargs)`; both resolve through this one injected module, so a single fake
    covers the real client code path too.
    """

    def _install(
        *,
        auth_check_result: bool = True,
        auth_check_raises: BaseException | None = None,
        score_raises: BaseException | None = None,
        flush_raises: BaseException | None = None,
    ) -> dict:
        calls: dict = {"scores": [], "flushes": 0}

        class _FakeLangfuse:
            def __init__(self, **kwargs) -> None:
                calls.setdefault("init_kwargs", []).append(kwargs)

            def auth_check(self) -> bool:
                if auth_check_raises:
                    raise auth_check_raises
                return auth_check_result

            def create_score(self, **kwargs) -> None:
                if score_raises:
                    raise score_raises
                calls["scores"].append(kwargs)

            # The adapter may use either name depending on SDK version.
            score = create_score

            def flush(self) -> None:
                if flush_raises:
                    raise flush_raises
                calls["flushes"] += 1

        module = types.ModuleType("langfuse")
        module.Langfuse = _FakeLangfuse  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "langfuse", module)
        return calls

    return _install


@pytest.fixture
def no_truststore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "truststore", None)


@pytest.fixture
def with_truststore(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("truststore")
    fake.inject_into_ssl = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "truststore", fake)


class TestCredentialGating:
    def test_skips_when_all_credentials_absent(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        for name in ls.REQUIRED_ENV:
            monkeypatch.delenv(name, raising=False)
        assert ls.main() == lib.SKIP_EXIT_CODE
        out = capsys.readouterr().out
        assert "SKIP" in out
        for name in ls.REQUIRED_ENV:
            assert name in out, "the SKIP line must name every unset variable"

    def test_skips_and_names_only_the_missing_one(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET_SENTINEL)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC_SENTINEL)
        monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
        assert ls.main() == lib.SKIP_EXIT_CODE
        out = capsys.readouterr().out
        assert "LANGFUSE_BASE_URL" in out
        assert "LANGFUSE_SECRET_KEY" not in out


class TestAuthCheck:
    def test_fails_when_auth_check_returns_false(self, creds, fake_langfuse, capsys) -> None:
        fake_langfuse(auth_check_result=False)
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "credentials rejected" in capsys.readouterr().out

    def test_fails_when_auth_check_raises(self, creds, fake_langfuse, capsys) -> None:
        fake_langfuse(auth_check_raises=RuntimeError("backend down"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        out = capsys.readouterr().out
        assert "RuntimeError" in out and "backend down" in out

    def test_tls_failure_without_truststore_suggests_it(self, creds, fake_langfuse, no_truststore, capsys) -> None:
        fake_langfuse(auth_check_raises=RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED] bad chain"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "pip install truststore" in capsys.readouterr().out

    def test_tls_failure_with_truststore_omits_the_hint(self, creds, fake_langfuse, with_truststore, capsys) -> None:
        """Already using the OS trust store, so recommending it would be noise."""
        fake_langfuse(auth_check_raises=RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED] bad chain"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "pip install truststore" not in capsys.readouterr().out

    def test_non_tls_failure_omits_the_hint(self, creds, fake_langfuse, no_truststore, capsys) -> None:
        fake_langfuse(auth_check_raises=RuntimeError("connection reset"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "pip install truststore" not in capsys.readouterr().out


class TestImportFailure:
    def test_fails_when_langfuse_sdk_absent(self, creds, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setitem(sys.modules, "langfuse", None)
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "cannot import client" in capsys.readouterr().out


class TestSuccess:
    def test_success_returns_zero_and_reports_the_host(self, creds, fake_langfuse, capsys) -> None:
        fake_langfuse()
        assert ls.main() == lib.OK_EXIT_CODE
        out = capsys.readouterr().out
        assert "OK" in out
        assert ls.SCORE_NAME in out
        assert BASE_URL in out, "the host is not a secret and identifies which backend was reached"

    def test_run_id_differs_between_invocations(self, creds, fake_langfuse, capsys) -> None:
        """Guards against someone replacing the uuid with a constant."""
        fake_langfuse()
        ls.main()
        first = capsys.readouterr().out
        fake_langfuse()
        ls.main()
        second = capsys.readouterr().out
        assert first != second

    def test_success_actually_writes_a_score(self, creds, fake_langfuse) -> None:
        """Non-vacuous: assert the score reached the SDK, not merely that main() returned 0.
        The whole reason this smoke exists is that a clean exit proved nothing."""
        calls = fake_langfuse()
        assert ls.main() == lib.OK_EXIT_CODE
        assert len(calls["scores"]) == 1
        assert calls["scores"][0]["name"] == ls.SCORE_NAME
        assert calls["flushes"] == 1


class TestSinkFailures:
    """auth_check passes but the score write itself fails -- the SDK is reachable and
    authenticated, yet the sink path is broken. Must still be a FAIL, not a green."""

    def test_fails_when_score_write_raises(self, creds, fake_langfuse, capsys) -> None:
        fake_langfuse(score_raises=RuntimeError("score rejected"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        out = capsys.readouterr().out
        assert "RuntimeError" in out and "score rejected" in out

    def test_fails_when_flush_raises(self, creds, fake_langfuse, capsys) -> None:
        fake_langfuse(flush_raises=RuntimeError("drain failed"))
        assert ls.main() == lib.FAIL_EXIT_CODE
        assert "drain failed" in capsys.readouterr().out


class TestNoCredentialLeak:
    @pytest.mark.parametrize(
        "scenario",
        ["skip", "import_error", "auth_false", "auth_raises", "success"],
    )
    def test_no_credential_value_is_ever_printed(
        self, scenario, creds, fake_langfuse, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """The module promises no credential value is printed at any level. Assert it on
        every reachable exit path, not just the one that happens to be convenient."""
        if scenario == "skip":
            monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        elif scenario == "import_error":
            monkeypatch.setitem(sys.modules, "langfuse", None)
        elif scenario == "auth_false":
            fake_langfuse(auth_check_result=False)
        elif scenario == "auth_raises":
            fake_langfuse(auth_check_raises=RuntimeError(f"rejected key {SECRET_SENTINEL[:4]}..."))
        else:
            fake_langfuse()

        ls.main()
        out = capsys.readouterr().out
        assert SECRET_SENTINEL not in out
        assert PUBLIC_SENTINEL not in out
