"""Unit tests for the P1 deploy phase orchestration (fully faked docker + health)."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from backend_validation.deploy_phase import http_health_check, run_deploy, run_down, run_status
from backend_validation.phases import STATUS_BLOCKED, STATUS_FAIL, STATUS_OK
from backend_validation.procrun import CompletedCommand
from backend_validation.settings import Settings, load_settings

SUBTREE = Path(__file__).resolve().parents[1]
_PINNED = "img@sha256:" + "a" * 64
_MANIFEST_STATS = json.dumps({"CPUPerc": "5%", "MemUsage": "50MiB / 2GiB"})


class FakeRunner:
    """Every docker invocation succeeds; stats/ps/inspect return canned output."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
        self.calls.append(list(argv))
        if "stats" in argv:
            return CompletedCommand(tuple(argv), 0, stdout=_MANIFEST_STATS)
        if "ps" in argv:
            return CompletedCommand(tuple(argv), 0, stdout="c1\nc2\n")
        if "inspect" in argv:
            return CompletedCommand(tuple(argv), 0, stdout="1000\n")
        return CompletedCommand(tuple(argv), 0)


def _pinned_settings(tmp_subtree: Path, *, include_judge: bool = True) -> Settings:
    # Rewrite the committed compose files to pinned images so the digest gate passes.
    for name, service in (("langfuse", "web"), ("opik", "web"), *((("judge", "ollama"),) if include_judge else ())):
        compose = tmp_subtree / "deploy" / name / "compose.yaml"
        compose.parent.mkdir(parents=True, exist_ok=True)
        compose.write_text(f"services:\n  {service}:\n    image: {_PINNED}\n", encoding="utf-8")
    return load_settings(tmp_subtree / "config.yaml", env={})


def test_deploy_happy_path_writes_effort_metrics(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    runner = FakeRunner()
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-1",
        runner=runner,
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "2026-07-20T00:00:00+00:00",
        stats_samples=1,
        stats_interval_seconds=0,
    )
    assert result.status == STATUS_OK, result.reason
    metrics_path = Path(result.artifacts[0])
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    backends = {entry["backend"] for entry in payload["backends"]}
    assert backends == {"langfuse", "opik", "judge"}  # the judge deploys with the fleet (M6a)
    assert all(entry["all_images_pinned"] for entry in payload["backends"])
    assert str(tmp_subtree) in str(metrics_path)  # metrics stay inside the subtree


def test_deploy_creates_shared_judge_network_before_any_up(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    runner = FakeRunner()
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-net",
        runner=runner,
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
        stats_samples=1,
        stats_interval_seconds=0,
    )
    assert result.status == STATUS_OK, result.reason
    # Every compose file declares bv-judge-net `external: true`, so the ensure-create
    # must be the FIRST docker call — before any stack's `up`.
    assert runner.calls[0] == ["docker", "network", "create", "bv-judge-net"]
    first_up = next(index for index, argv in enumerate(runner.calls) if "up" in argv)
    assert first_up > 0


def test_deploy_tolerates_existing_judge_network(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)

    class NetworkExists(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            result = super().run(argv, **kwargs)
            if argv[:3] == ["docker", "network", "create"]:
                return CompletedCommand(tuple(argv), 1, stderr='network with name "bv-judge-net" already exists')
            return result

    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-net-exists",
        runner=NetworkExists(),
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
        stats_samples=1,
        stats_interval_seconds=0,
    )
    assert result.status == STATUS_OK, result.reason  # idempotent, not a failure


def test_deploy_blocks_when_judge_network_cannot_be_created(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)

    class NetworkBroken(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            result = super().run(argv, **kwargs)
            if argv[:3] == ["docker", "network", "create"]:
                return CompletedCommand(tuple(argv), 1, stderr="Error response from daemon: address pool exhausted")
            return result

    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-net-broken",
        runner=NetworkBroken(),
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
    )
    assert result.status == STATUS_BLOCKED
    assert "cannot create the shared judge network" in result.reason
    assert "bv-judge-net" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_deploy_pulls_judge_model_after_health(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    runner = FakeRunner()
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-judge",
        runner=runner,
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
        stats_samples=1,
        stats_interval_seconds=0,
    )
    assert result.status == STATUS_OK, result.reason
    judge_compose = tmp_subtree / "deploy" / "judge" / "compose.yaml"
    expected_pull = [
        "docker",
        "compose",
        "-f",
        str(judge_compose),
        "-p",
        "bv-judge",
        "exec",
        "-T",
        "ollama",
        "ollama",
        "pull",
        "llama3.2:3b",  # config.yaml default for ${BV_JUDGE_MODEL}
    ]
    assert expected_pull in runner.calls
    up_calls = [argv for argv in runner.calls if "up" in argv and "bv-judge" in argv]
    assert up_calls and runner.calls.index(up_calls[0]) < runner.calls.index(expected_pull)  # pull AFTER up


def test_deploy_blocks_when_judge_model_pull_fails(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)

    class PullFails(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            result = super().run(argv, **kwargs)
            if "pull" in argv:
                return CompletedCommand(tuple(argv), 1, stderr="model not found")
            return result

    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-pullfail",
        runner=PullFails(),
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
    )
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "judge model pull failed" in result.reason and "llama3.2:3b" in result.reason
    assert "judge" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_deploy_blocks_on_unpinned_judge_compose(tmp_subtree: Path) -> None:
    # Backends pinned but the judge compose regains a TODO_PIN marker (the committed
    # file ships pinned): the digest gate applies to the judge stack exactly as it
    # does to the backends.
    (tmp_subtree / "deploy" / "judge" / "compose.yaml").write_text(
        "name: bv-judge\nservices:\n  ollama:\n    image: ollama/ollama:0.9.6@TODO_PIN\n",
        encoding="utf-8",
    )
    settings = _pinned_settings(tmp_subtree, include_judge=False)
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-judge-unpinned",
        runner=FakeRunner(),
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
    )
    assert result.status == STATUS_BLOCKED
    assert "pin-digests" in result.reason
    assert "deploy (P1) — judge" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_deploy_blocks_on_unpinned_committed_compose(tmp_subtree: Path) -> None:
    # The committed composes ship pinned; recreate the unpinned state explicitly to
    # prove the digest gate still BLOCKs a deploy the moment a marker reappears.
    (tmp_subtree / "deploy" / "langfuse" / "compose.yaml").write_text(
        "name: bv-langfuse\nservices:\n  langfuse-web:\n    image: langfuse/langfuse:3@TODO_PIN\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_subtree / "config.yaml", env={})
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-2",
        runner=FakeRunner(),
        only_backend="langfuse",
        health_check=lambda _url: True,
        now_fn=lambda: "t",
    )
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "pin-digests" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_deploy_unknown_backend_fails(tmp_subtree: Path) -> None:
    result = run_deploy(
        tmp_subtree,
        load_settings(tmp_subtree / "config.yaml", env={}),
        env={},
        run_id="r",
        only_backend="mlflow",
        runner=FakeRunner(),
        now_fn=lambda: "t",
    )
    assert result.status == STATUS_FAIL


def test_down_reports_teardown(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    runner = FakeRunner()
    ok = run_down(tmp_subtree, settings, runner=runner)
    assert ok.status == STATUS_OK
    # The full-fleet down tears the judge stack too, then best-effort removes the shared
    # network LAST (external networks survive compose down).
    assert any("bv-judge" in argv and "down" in argv for argv in runner.calls)
    assert runner.calls[-1] == ["docker", "network", "rm", "bv-judge-net"]

    class FailRunner(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            super().run(argv, **kwargs)
            return CompletedCommand(tuple(argv), 1)

    fail_runner = FailRunner()
    failed = run_down(tmp_subtree, settings, runner=fail_runner, only_backend="opik")
    assert failed.status == STATUS_FAIL and "opik" in failed.reason
    assert "judge" not in failed.reason  # --backend-scoped down leaves the shared judge alone
    # The network rm still ran and its failure was ignored (containers may be attached).
    assert fail_runner.calls[-1] == ["docker", "network", "rm", "bv-judge-net"]


def test_http_health_check_against_loopback_server() -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_a: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert http_health_check(f"http://127.0.0.1:{server.server_port}/") is True
    finally:
        server.shutdown()
        thread.join(timeout=5)
    # Nothing listening on port 1 -> unhealthy, no exception.
    assert http_health_check("http://127.0.0.1:1/") is False


def test_deploy_fails_loud_when_existing_metrics_are_corrupt(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    reports = tmp_subtree / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "effort_metrics.json").write_text("{not json", encoding="utf-8")
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-corrupt-metrics",
        runner=FakeRunner(),
        health_check=lambda _url: True,
        clock=iter([float(i) for i in range(20)]).__next__,
        sleeper=lambda _s: None,
        now_fn=lambda: "t",
        stats_samples=1,
        stats_interval_seconds=0,
    )
    assert result.status == STATUS_FAIL and "effort metrics invalid" in result.reason


# ---------------------------------------------------------------------- status
def test_status_reports_counts_across_all_projects(tmp_subtree: Path) -> None:
    settings = load_settings(tmp_subtree / "config.yaml", env={})
    runner = FakeRunner()
    result = run_status(tmp_subtree, settings, runner=runner)
    assert result.status == STATUS_OK
    # Normal projects, the judge, then the airgap twins — each with the fake's 2 containers.
    for project in ("bv-langfuse", "bv-opik", "bv-judge", "bv-langfuse-airgap", "bv-opik-airgap"):
        assert f"{project}: 2 container(s)" in result.reason
    ps_filters = [argv for argv in runner.calls if "ps" in argv]
    assert len(ps_filters) == 5
    assert ["docker", "--version"] in runner.calls  # docker probed before any ps


def test_status_blocks_without_docker(tmp_subtree: Path) -> None:
    class NoDocker(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            super().run(argv, **kwargs)
            return CompletedCommand(tuple(argv), 127, stderr="docker: command not found")

    settings = load_settings(tmp_subtree / "config.yaml", env={})
    result = run_status(tmp_subtree, settings, runner=NoDocker())
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "docker is not available" in result.reason


def test_status_blocks_when_docker_ps_fails(tmp_subtree: Path) -> None:
    class DaemonDown(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            result = super().run(argv, **kwargs)
            if "ps" in argv:
                return CompletedCommand(tuple(argv), 1, stderr="cannot connect to the docker daemon")
            return result

    settings = load_settings(tmp_subtree / "config.yaml", env={})
    result = run_status(tmp_subtree, settings, runner=DaemonDown())
    assert result.status == STATUS_BLOCKED
    assert "docker ps failed for bv-langfuse" in result.reason


def test_http_health_check_uses_tls_for_https(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression (Gemini review): an https endpoint must use HTTPSConnection, not a plaintext
    # HTTPConnection (which would always fail the check against a real TLS stack).
    import http.client

    import backend_validation.deploy_phase as dp

    used: dict[str, object] = {}

    class _FakeConn:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            used["host"], used["port"] = host, port

        def request(self, *_a: object) -> None:
            return None

        def getresponse(self) -> object:
            return types.SimpleNamespace(status=200)

        def close(self) -> None:
            return None

    monkeypatch.setattr(http.client, "HTTPSConnection", _FakeConn)
    # If the code wrongly picked HTTPConnection, this sentinel would raise on use.
    monkeypatch.setattr(
        http.client, "HTTPConnection", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("http used"))
    )
    assert dp.http_health_check("https://stack.example:8443/health") is True
    assert used == {"host": "stack.example", "port": 8443}
