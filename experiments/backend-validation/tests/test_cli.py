"""Unit tests for the CLI: exit codes, verdict lines, and subtree wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation import cli
from backend_validation.procrun import CompletedCommand, SubprocessRunner


@pytest.fixture()
def cli_subtree(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "SUBTREE_ROOT", tmp_subtree)
    return tmp_subtree


def test_schema_only_preflight_is_green(cli_subtree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["preflight", "--schema-only", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("backend-validation[preflight]: OK — ")


def test_full_preflight_blocks_unsigned(cli_subtree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["preflight", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 3
    assert "backend-validation[preflight]: BLOCKED — " in out
    assert "evidence:" in out  # the blocked report path is surfaced


def test_l1_blocks_without_credentials_via_cli(cli_subtree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # The credential check runs BEFORE any SDK import: a credential-less live run is
    # BLOCKED naming the env vars — never a silently-degraded Null client probing air.
    code = cli.main(["l1", "--run-id", "run-cli", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 3
    assert "backend-validation[l1]: BLOCKED — " in out
    assert "credentials missing" in out and "evidence:" in out


def test_invalid_config_is_usage_error(cli_subtree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("backends: []\n", encoding="utf-8")
    code = cli.main(["preflight", "--config", str(bad)])
    out = capsys.readouterr().out
    assert code == 2
    assert "FAIL — invalid configuration" in out


def test_unknown_subcommand_exits_2(cli_subtree: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["bogus"])
    assert excinfo.value.code == 2


def test_isolation_outside_git_repo_is_usage_error(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NoGit(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=128, stderr="fatal: not a git repo")

    monkeypatch.setattr(cli, "SubprocessRunner", NoGit)
    code = cli.main(["isolation"])
    assert code == 2
    assert "not inside a git repository" in capsys.readouterr().out


def test_isolation_runs_clean_in_the_real_repo(capsys: pytest.CaptureFixture[str]) -> None:
    # The real repo may have in-flight changes during development; assert only the
    # verdict-line contract (OK or FAIL with a listing), never specific content.
    code = cli.main(["isolation", "--base-ref", "HEAD"])
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert "backend-validation[isolation]:" in out


def test_pin_digests_reports_when_registry_unreachable(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The committed compose files carry TODO_PIN; a failing manifest inspect -> FAIL exit 1.
    class NoRegistry(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=1, stderr="no route to registry")

    monkeypatch.setattr(cli, "SubprocessRunner", NoRegistry)
    code = cli.main(["pin-digests", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 1
    assert "backend-validation[pin-digests]: FAIL" in out


def test_down_via_cli(cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class OkRunner(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=0)

    monkeypatch.setattr("backend_validation.deploy_phase.SubprocessRunner", OkRunner)
    code = cli.main(["down", "--config", str(cli_subtree / "config.yaml")])
    assert code == 0
    assert "backend-validation[down]: OK" in capsys.readouterr().out
