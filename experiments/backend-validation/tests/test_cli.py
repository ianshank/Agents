"""Unit tests for the CLI: exit codes, verdict lines, and subtree wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation import cli
from backend_validation.phases import PhaseResult
from backend_validation.procrun import CompletedCommand, SubprocessRunner
from backend_validation.settings import load_settings


@pytest.fixture()
def cli_subtree(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(cli, "SUBTREE_ROOT", tmp_subtree)
    return tmp_subtree


class NoDocker(SubprocessRunner):
    """Every external command fails as if docker were absent from the host."""

    def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
        return CompletedCommand(tuple(argv), returncode=127, stderr="docker: command not found")


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


def test_airgap_blocks_without_docker_via_cli(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # exit 3 with a blocked report — never argparse exit 2 (the Makefile target contract).
    monkeypatch.setattr(cli, "SubprocessRunner", NoDocker)
    code = cli.main(["airgap", "--run-id", "run-cli-ag", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 3
    assert "backend-validation[airgap]: BLOCKED — docker is not available" in out
    assert "evidence:" in out
    assert (cli_subtree / "artifacts" / "run-cli-ag" / "blocked_report.md").exists()


def test_status_blocks_without_docker_via_cli(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("backend_validation.deploy_phase.SubprocessRunner", NoDocker)
    code = cli.main(["status", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 3
    assert "backend-validation[status]: BLOCKED — docker is not available" in out


def test_status_ok_via_cli(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class QuietDocker(SubprocessRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            return CompletedCommand(tuple(argv), returncode=0, stdout="")

    monkeypatch.setattr("backend_validation.deploy_phase.SubprocessRunner", QuietDocker)
    code = cli.main(["status", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 0
    assert "bv-langfuse: 0 container(s)" in out and "bv-opik-airgap: 0 container(s)" in out


def test_plain_all_chain_has_no_airgap_phase(cli_subtree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Without --with-airgap the chain is byte-identical to before: the unsigned tmp tree
    # blocks at preflight and no airgap verdict line ever appears.
    code = cli.main(["all", "--config", str(cli_subtree / "config.yaml")])
    out = capsys.readouterr().out
    assert code == 3
    assert "backend-validation[preflight]: BLOCKED" in out
    assert "[airgap]" not in out


def test_all_with_airgap_threads_the_adapter(
    cli_subtree: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorded: dict[str, object] = {}

    def fake_run_all(*_args: object, **kwargs: object) -> list[PhaseResult]:
        recorded.update(kwargs)
        return [PhaseResult("preflight", "OK", "stubbed")]

    monkeypatch.setattr(cli, "run_all", fake_run_all)
    assert cli.main(["all", "--with-airgap", "--config", str(cli_subtree / "config.yaml")]) == 0
    threaded = recorded.pop("airgap_runner")
    assert threaded is cli._airgap_runner  # the seam is threaded...
    assert cli.main(["all", "--config", str(cli_subtree / "config.yaml")]) == 0
    defaulted = recorded.pop("airgap_runner")
    assert defaulted is None  # ...and absent by default
    capsys.readouterr()


def test_airgap_runner_adapter_returns_phase_result(cli_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The adapter the chain injects builds real IO around run_airgap; under a docker-less
    # runner it produces the same BLOCKED PhaseResult the standalone subcommand would.
    monkeypatch.setattr(cli, "SubprocessRunner", NoDocker)
    settings = load_settings(cli_subtree / "config.yaml", env={})
    result = cli._airgap_runner(cli_subtree, settings, run_id="run-adapter", now_fn=lambda: "t")
    assert result.phase == "airgap" and result.status == "BLOCKED"
    assert "docker is not available" in result.reason
