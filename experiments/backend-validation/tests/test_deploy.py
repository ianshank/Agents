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


def test_bind_mounts_inside_catches_dotdot_escape(tmp_path: Path) -> None:
    # Regression (Gemini review): a `../` source is NOT a named volume — it must be checked
    # for containment, not skipped. The compose file lives in tmp/sub so `../../etc` escapes.
    sub = tmp_path / "sub"
    sub.mkdir()
    for source in ("../../etc:/data", "..:/data", "../sibling:/data"):
        compose = _compose(sub, f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - {source}\n")
        violations = bind_mounts_inside(compose, tmp_path / "sub")
        assert violations and "escapes the subtree" in violations[0], f"{source} slipped through"
    # A dotted path that stays inside is still allowed.
    inside = _compose(sub, f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - ./nested/data:/data\n")
    assert bind_mounts_inside(inside, tmp_path / "sub") == []


def test_bind_mounts_inside_flags_escaping_long_form_source(tmp_path: Path) -> None:
    # Long-form volume ({type: bind, source: ...}) with an escaping source is flagged too.
    sub = tmp_path / "sub"
    sub.mkdir()
    compose = _compose(
        sub,
        f"services:\n  a:\n    image: {_PINNED}\n    volumes:\n      - {{type: bind, source: '../out', target: /x}}\n",
    )
    assert any("escapes the subtree" in v for v in bind_mounts_inside(compose, sub))


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
    assert outcome.images[0].pinned


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


# ------------------------------------------------- committed stack shape (Opik + P4)
def test_opik_compose_declares_guardrails_and_python_health() -> None:
    """The committed Opik stack carries the guardrails cell and the health wiring the
    probes rely on — incl. the nginx conf mount without which nothing listens on 5173."""
    import yaml

    data = yaml.safe_load((SUBTREE / "deploy" / "opik" / "compose.yaml").read_text(encoding="utf-8"))
    services = data["services"]
    guardrails = services["guardrails"]
    assert guardrails["image"].startswith("ghcr.io/comet-ml/opik/opik-guardrails-backend:1.7.26@")
    assert guardrails["hostname"] == "guardrails"  # nginx proxies /guardrails/ -> guardrails:5000
    assert "127.0.0.1:5000/healthcheck" in " ".join(guardrails["healthcheck"]["test"])
    assert "ports" not in guardrails  # reachable only through the frontend proxy
    assert "healthcheck" in services["opik-python-backend"]
    # The 1.7.26 python backend never reads the usage-report lever — it must not carry it.
    assert "OPIK_USAGE_REPORT_ENABLED" not in services["opik-python-backend"].get("environment", {})
    frontend = services["opik-frontend"]
    assert "opik-python-backend" in frontend["depends_on"]
    assert any(
        volume.startswith("./nginx_guardrails_local.conf:/etc/nginx/conf.d/default.conf")
        for volume in frontend["volumes"]
    )
    backend_env = services["opik-backend"]["environment"]
    assert backend_env["PYTHON_EVALUATOR_URL"] == "http://opik-python-backend:8000"
    assert backend_env["TOGGLE_GUARDRAILS_ENABLED"] == "true"


def _overlay_service_blocks(text: str) -> dict[str, str]:
    """Split an overlay's top-level `services:` mapping into raw text per service.

    Deliberately textual: the overlays carry the compose `!reset` tag, which
    yaml.safe_load rejects — the contract must be pinned against the committed bytes.
    """
    blocks: dict[str, str] = {}
    current: str | None = None
    in_services = False
    for line in text.splitlines():
        stripped = line.strip()
        if line and not line[0].isspace():  # a new top-level key (or column-0 comment)
            in_services = line.startswith("services:")
            current = None
            continue
        if not in_services or not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current = stripped[:-1]
            blocks[current] = ""
        elif current is not None:
            blocks[current] += line + "\n"
    return blocks


def test_airgap_overlays_reset_published_ports_and_join_internal_network() -> None:
    """P4 overlay contract (validated at runtime by check_overlay; pinned here at text
    level): every base service joins ONLY the internal network (detaching the implicit
    default one), publishers strip their ports with the load-bearing `!reset` tag (a
    plain `ports: []` merges to a no-op), and app DNS points at the static witness."""
    import yaml

    for stack, network_name, ip_prefix in (
        ("langfuse", "bv-langfuse-internal", "172.31.100"),
        ("opik", "bv-opik-internal", "172.31.101"),
    ):
        base = yaml.safe_load((SUBTREE / "deploy" / stack / "compose.yaml").read_text(encoding="utf-8"))
        text = (SUBTREE / "deploy" / stack / "compose.airgap.yaml").read_text(encoding="utf-8")
        blocks = _overlay_service_blocks(text)
        for name, service in base["services"].items():
            assert name in blocks, f"{stack} overlay must enumerate {name} to detach the default network"
            # Services with EXPLICIT base networks (the judge-net attachees) must use
            # `!override`: compose UNIONS explicit network lists on merge, so a plain
            # [bv-internal] would leave the shared judge network attached inside the seal.
            expected_networks = (
                "networks: !override [bv-internal]" if service.get("networks") else "networks: [bv-internal]"
            )
            assert expected_networks in blocks[name], f"{stack}:{name} wants {expected_networks!r}"
            assert f"dns: [{ip_prefix}.53]" in blocks[name], f"{stack}:{name}"
            assert "bv-dns-witness: {condition: service_started}" in blocks[name], f"{stack}:{name}"
        publishers = [name for name, service in base["services"].items() if service.get("ports")]
        assert publishers, f"{stack} base compose publishes no ports — overlay test is stale"
        for name in publishers:
            assert "ports: !reset []" in blocks[name], f"{stack}:{name} must !reset its published ports"
        witness = blocks["bv-dns-witness"]
        assert "image: coredns/coredns:1.12.1@" in witness
        assert "- ../witness/Corefile:/etc/coredns/Corefile:ro" in witness
        assert f"ipv4_address: {ip_prefix}.53" in witness
        # The witness must not point DNS at itself (line-anchored: the coredns image
        # ref legitimately contains the substring "dns:").
        assert not any(line.strip().startswith("dns:") for line in witness.splitlines())
        assert "internal: true" in text and f"name: {network_name}" in text
