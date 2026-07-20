"""Unit tests for the P1 deploy phase orchestration (fully faked docker + health)."""

from __future__ import annotations

import json
from pathlib import Path

from backend_validation.deploy_phase import http_health_check, run_deploy, run_down
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


def _pinned_settings(tmp_subtree: Path) -> Settings:
    # Rewrite the committed compose files to pinned images so the digest gate passes.
    for name in ("langfuse", "opik"):
        compose = tmp_subtree / "deploy" / name / "compose.yaml"
        compose.parent.mkdir(parents=True, exist_ok=True)
        compose.write_text(f"services:\n  web:\n    image: {_PINNED}\n", encoding="utf-8")
    return load_settings(tmp_subtree / "config.yaml", env={})


def test_deploy_happy_path_writes_effort_metrics(tmp_subtree: Path) -> None:
    settings = _pinned_settings(tmp_subtree)
    result = run_deploy(
        tmp_subtree,
        settings,
        env={},
        run_id="run-1",
        runner=FakeRunner(),
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
    assert backends == {"langfuse", "opik"}
    assert all(entry["all_images_pinned"] for entry in payload["backends"])
    assert str(tmp_subtree) in str(metrics_path)  # metrics stay inside the subtree


def test_deploy_blocks_on_unpinned_committed_compose(tmp_subtree: Path) -> None:
    # The real committed compose files (copied by the fixture) carry TODO_PIN, so the
    # digest gate BLOCKs without any test-local rewrite.
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
    ok = run_down(tmp_subtree, settings, runner=FakeRunner())
    assert ok.status == STATUS_OK

    class FailRunner(FakeRunner):
        def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
            super().run(argv, **kwargs)
            return CompletedCommand(tuple(argv), 1)

    failed = run_down(tmp_subtree, settings, runner=FailRunner(), only_backend="opik")
    assert failed.status == STATUS_FAIL and "opik" in failed.reason


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
