"""Unit tests for compose parsing, the digest gate, bind-mount containment, and pinning."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation.deploy import (
    DeployError,
    bind_mounts_inside,
    compose_argv,
    compose_images,
    deploy_stack,
    down_stack,
    pin_compose_file,
    refuse_unpinned,
    resolve_digest,
)
from backend_validation.procrun import CompletedCommand
from backend_validation.settings import BackendSpec, Settings, load_settings

SUBTREE = Path(__file__).resolve().parents[1]
_PINNED = "postgres:16@sha256:" + "a" * 64


class ScriptedRunner:
    """CommandRunner double: returns queued results, records argv."""

    def __init__(self, results: list[CompletedCommand]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
        self.calls.append(list(argv))
        return self._results.pop(0) if self._results else CompletedCommand(tuple(argv), 0)


def _compose(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "compose.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _spec(tmp_path: Path) -> BackendSpec:
    return BackendSpec(
        id="langfuse",
        display_name="Langfuse",
        base_url="http://127.0.0.1:18321",
        compose_file="compose.yaml",
        sdk_extra="langfuse",
    )


def _settings() -> Settings:
    return load_settings(SUBTREE / "config.yaml", env={})


# --------------------------------------------------------------- compose parsing
def test_compose_images_sorted_and_typed(tmp_path: Path) -> None:
    path = _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n  db:\n    image: redis:7@sha256:{'b' * 64}\n")
    images = compose_images(path)
    assert [image.service for image in images] == ["db", "web"]  # sorted for byte-stability
    assert images[1].pinned and images[1].digest == "sha256:" + "a" * 64


def test_compose_without_services_or_image_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="no services"):
        compose_images(_compose(tmp_path, "version: '3'\n"))
    with pytest.raises(DeployError, match="has no image"):
        compose_images(_compose(tmp_path, "services:\n  web:\n    build: .\n"))
    with pytest.raises(DeployError, match="not valid YAML"):
        compose_images(_compose(tmp_path, "services: [unclosed\n"))


# ------------------------------------------------------------------ digest gate
def test_refuse_unpinned_blocks_tag_only_images(tmp_path: Path) -> None:
    path = _compose(tmp_path, "services:\n  web:\n    image: postgres:16-alpine\n")
    with pytest.raises(DeployError, match="unpinned image"):
        refuse_unpinned(path)


def test_refuse_unpinned_blocks_todo_markers(tmp_path: Path) -> None:
    path = _compose(tmp_path, "services:\n  web:\n    image: postgres:16@TODO_PIN\n")
    with pytest.raises(DeployError, match="pin-digests"):
        refuse_unpinned(path)


def test_refuse_unpinned_accepts_digest(tmp_path: Path) -> None:
    path = _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n")
    assert refuse_unpinned(path)[0].pinned


def test_committed_compose_files_are_currently_todo_pinned() -> None:
    # Ships with TODO_PIN markers; `make pin-digests` resolves them where the registry is
    # reachable. This test documents the state AND proves the gate would refuse a deploy.
    for name in ("langfuse", "opik", "judge"):
        path = SUBTREE / "deploy" / name / "compose.yaml"
        with pytest.raises(DeployError, match="pin-digests"):
            refuse_unpinned(path)


# ---------------------------------------------------------------- bind mounts
def test_bind_mounts_inside_flags_escaping_host_mount(tmp_path: Path) -> None:
    inside = _compose(tmp_path, f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - ./data:/data\n")
    assert bind_mounts_inside(inside, tmp_path) == []
    named = _compose(tmp_path, f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - vol:/data\n")
    assert bind_mounts_inside(named, tmp_path) == []  # named volume is fine
    escaping = _compose(tmp_path, f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - /etc:/data\n")
    violations = bind_mounts_inside(escaping, tmp_path)
    assert violations and "escapes the subtree" in violations[0]


# --------------------------------------------------------------------- argv
def test_compose_argv_uses_project_name(tmp_path: Path) -> None:
    argv = compose_argv(tmp_path / "compose.yaml", "opik", "up", "-d")
    assert argv[:3] == ["docker", "compose", "-f"] and "bv-opik" in argv


# ------------------------------------------------------------------ deploy_stack
def test_deploy_stack_happy_path_counts_health_retries(tmp_path: Path) -> None:
    _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n")
    spec = _spec(tmp_path)
    runner = ScriptedRunner([CompletedCommand(("docker",), 0)])
    healths = iter([False, False, True])
    outcome = deploy_stack(
        spec,
        _settings(),
        tmp_path,
        runner,
        env={},
        health_check=lambda _url: next(healths),
        clock=iter([10.0, 25.0]).__next__,
        sleeper=lambda _s: None,
    )
    assert outcome.health_retries == 2 and outcome.setup_wall_clock_seconds == 15.0
    assert outcome.failure_count == 0 and outcome.images[0].pinned


def test_deploy_stack_blocks_on_compose_up_failure(tmp_path: Path) -> None:
    _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n")
    runner = ScriptedRunner([CompletedCommand(("docker",), 1, stderr="boom")])
    with pytest.raises(DeployError, match="compose up for langfuse failed"):
        deploy_stack(
            _spec(tmp_path),
            _settings(),
            tmp_path,
            runner,
            env={},
            health_check=lambda _url: True,
            clock=iter([0.0, 1.0]).__next__,
            sleeper=lambda _s: None,
        )


def test_deploy_stack_blocks_when_app_never_healthy(tmp_path: Path) -> None:
    _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n")
    runner = ScriptedRunner([CompletedCommand(("docker",), 0)])
    with pytest.raises(DeployError, match="never answered"):
        deploy_stack(
            _spec(tmp_path),
            _settings(),
            tmp_path,
            runner,
            env={},
            health_check=lambda _url: False,
            clock=iter([0.0] * 10).__next__,
            sleeper=lambda _s: None,
            health_attempts=2,
        )


def test_down_stack(tmp_path: Path) -> None:
    _compose(tmp_path, f"services:\n  web:\n    image: {_PINNED}\n")
    runner = ScriptedRunner([CompletedCommand(("docker",), 0)])
    assert down_stack(_spec(tmp_path), tmp_path, runner) is True
    assert runner.calls[0][4:7] == ["-p", "bv-langfuse", "down"]  # after `docker compose -f <path>`


# ----------------------------------------------------------------- pinning
_MANIFEST = '{"Descriptor": {"digest": "sha256:' + "c" * 64 + '"}}'


def test_resolve_digest_extracts_from_manifest() -> None:
    runner = ScriptedRunner([CompletedCommand(("docker",), 0, stdout=_MANIFEST)])
    assert resolve_digest("postgres:16", runner) == "sha256:" + "c" * 64


def test_resolve_digest_errors() -> None:
    with pytest.raises(DeployError, match="manifest inspect failed"):
        resolve_digest("x", ScriptedRunner([CompletedCommand(("docker",), 1, stderr="no such image")]))
    with pytest.raises(DeployError, match="no digest found"):
        resolve_digest("x", ScriptedRunner([CompletedCommand(("docker",), 0, stdout="{}")]))


def test_pin_compose_file_rewrites_only_image_lines(tmp_path: Path) -> None:
    path = _compose(
        tmp_path,
        "services:\n  web:\n    image: postgres:16@TODO_PIN\n    ports:\n      - 1:2\n"
        f"  cached:\n    image: {_PINNED}\n",
    )
    runner = ScriptedRunner([CompletedCommand(("docker",), 0, stdout=_MANIFEST)])
    pinned = pin_compose_file(path, runner)
    assert pinned == [("postgres:16", "sha256:" + "c" * 64)]  # only the TODO line resolved
    body = path.read_text(encoding="utf-8")
    assert "postgres:16@sha256:" + "c" * 64 in body
    assert _PINNED in body  # already-pinned line untouched
    assert "ports:" in body  # non-image lines untouched
