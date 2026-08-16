"""Unit tests for the P4 orchestrator: builders, overlay gate, iptables contract, flow.

Everything runs offline through scripted CommandRunners; the scenario table mirrors the
plan's Test plan -> C rows (docker absent, gate violations, build/up failures, prober rc
mapping, dead witness, detected egress, iptables None-branches, happy dual-run).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend_validation.airgap_phase import (
    _RESET,
    WITNESS_SERVICE,
    AirgapIO,
    _gate_backend,
    airgap_compose_argv,
    airgap_project_name,
    canary_run_argv,
    check_overlay,
    collect_container_logs,
    collect_witness_log,
    dockerfile_pinned,
    internal_network_name,
    load_overlay,
    overlay_path,
    overlay_witness_ip,
    prober_build_argv,
    prober_env_pairs,
    prober_run_argv,
    read_iptables_egress_hits,
    run_airgap,
)
from backend_validation.deploy import refuse_unpinned
from backend_validation.phases import STATUS_BLOCKED, STATUS_FAIL, STATUS_HALT, STATUS_OK
from backend_validation.procrun import CompletedCommand
from backend_validation.settings import BackendSpec, Settings, load_settings

SUBTREE = Path(__file__).resolve().parents[1]
_PINNED = "img@sha256:" + "a" * 64
_WITNESS_PINNED = "coredns/coredns:1.12.1@sha256:" + "b" * 64
_WITNESS_IP = "172.31.101.53"
_NET_ID = "f" * 64
_BRIDGE = f"br-{'f' * 12}"

# A live-witness log whose ONLY line is the canary (the clean-run steady state, B1).
_CANARY_WITNESS = (
    '[INFO] 172.31.101.9:41210 - 7 "A IN bv-witness-canary.invalid. udp 54 false 512" NXDOMAIN qr,aa,rd 110 0.0001s\n'
)
_LEAKY_WITNESS = (
    _CANARY_WITNESS
    + '[INFO] 172.31.101.5:53535 - 8 "A IN stats.comet.com. udp 45 false 512" NXDOMAIN qr,aa,rd 106 0.0002s\n'
)
_IPTABLES_CLEAN = (
    "Chain DOCKER-ISOLATION-STAGE-1 (1 references)\n"
    "    pkts      bytes target     prot opt in     out     source               destination\n"
    f"       0        0 DROP       all  --  {_BRIDGE} !{_BRIDGE}  0.0.0.0/0            0.0.0.0/0\n"
    f"       0        0 DROP       all  --  !{_BRIDGE} {_BRIDGE}  0.0.0.0/0            0.0.0.0/0\n"
)


def _spec(backend_id: str = "langfuse", **overrides: object) -> BackendSpec:
    payload: dict[str, object] = {
        "id": backend_id,
        "display_name": backend_id,
        "base_url": "http://127.0.0.1:1",
        "compose_file": f"deploy/{backend_id}/compose.yaml",
        "sdk_extra": backend_id,
    }
    payload.update(overrides)
    return BackendSpec.model_validate(payload)


# ---------------------------------------------------------------- exact-argv builders
def test_naming_builders_are_deterministic() -> None:
    assert airgap_project_name("langfuse") == "bv-langfuse-airgap"
    assert internal_network_name("opik") == "bv-opik-internal"


def test_overlay_path_sits_next_to_the_base_compose(tmp_path: Path) -> None:
    assert overlay_path(tmp_path, _spec("opik")) == tmp_path / "deploy" / "opik" / "compose.airgap.yaml"


def test_airgap_compose_argv_layers_base_then_overlay(tmp_path: Path) -> None:
    base, overlay = tmp_path / "compose.yaml", tmp_path / "compose.airgap.yaml"
    assert airgap_compose_argv(base, overlay, "langfuse", "up", "-d") == [
        "docker",
        "compose",
        "-f",
        str(base),
        "-f",
        str(overlay),
        "-p",
        "bv-langfuse-airgap",
        "up",
        "-d",
    ]


def test_prober_build_argv_is_exact(tmp_path: Path) -> None:
    assert prober_build_argv(tmp_path, "run-7") == [
        "docker",
        "build",
        "-f",
        str(tmp_path / "deploy" / "prober" / "Dockerfile"),
        "-t",
        "bv-prober:run-7",
        str(tmp_path),
    ]


def test_canary_run_argv_is_exact_and_dnsed_at_the_witness() -> None:
    argv = canary_run_argv("langfuse", "run-7", _WITNESS_IP)
    assert argv[:9] == [
        "docker",
        "run",
        "--rm",
        "--network",
        "bv-langfuse-internal",
        "--dns",
        _WITNESS_IP,
        "--entrypoint",
        "python",
    ]
    assert argv[9] == "bv-prober:run-7" and argv[10] == "-c"
    assert "bv-witness-canary.invalid" in argv[11] and "getaddrinfo" in argv[11]
    assert "suppress(OSError)" in argv[11]  # exceptions swallowed: NXDOMAIN is the expected answer


def test_prober_env_pairs_langfuse_exact_set_and_order() -> None:
    spec = _spec(credential_env={"secret_key": "BV_LANGFUSE_SECRET_KEY", "public_key": "BV_LANGFUSE_PUBLIC_KEY"})
    env = {"BV_LANGFUSE_SECRET_KEY": "sk-1", "BV_LANGFUSE_PUBLIC_KEY": "pk-1", "UNRELATED": "x"}
    assert prober_env_pairs(spec, env) == [
        ("BV_LANGFUSE_HOST", "langfuse-web"),
        ("BV_LANGFUSE_PORT", "3000"),
        ("BV_LANGFUSE_SECRET_KEY", "sk-1"),
        ("BV_LANGFUSE_PUBLIC_KEY", "pk-1"),
    ]


def test_prober_env_pairs_missing_credentials_are_omitted_not_raised() -> None:
    # The prober's own preflight turns the absent creds into ITS OWN BLOCKED (rc=3);
    # the builder must never KeyError or invent values.
    spec = _spec(credential_env={"secret_key": "BV_LANGFUSE_SECRET_KEY", "public_key": "BV_LANGFUSE_PUBLIC_KEY"})
    assert prober_env_pairs(spec, {}) == [("BV_LANGFUSE_HOST", "langfuse-web"), ("BV_LANGFUSE_PORT", "3000")]


def test_prober_env_pairs_opik_workspace_and_optional_api_key() -> None:
    spec = _spec("opik", credential_env={"api_key": "BV_OPIK_API_KEY"}, workspace="team-a")
    assert prober_env_pairs(spec, {}) == [
        ("BV_OPIK_HOST", "opik-frontend"),
        ("BV_OPIK_PORT", "5173"),
        ("BV_OPIK_WORKSPACE", "team-a"),
    ]
    assert prober_env_pairs(spec, {"BV_OPIK_API_KEY": "k"}) == [
        ("BV_OPIK_HOST", "opik-frontend"),
        ("BV_OPIK_PORT", "5173"),
        ("BV_OPIK_WORKSPACE", "team-a"),
        ("BV_OPIK_API_KEY", "k"),
    ]


def test_prober_run_argv_full_shape(tmp_path: Path) -> None:
    spec = _spec(credential_env={"secret_key": "BV_LANGFUSE_SECRET_KEY", "public_key": "BV_LANGFUSE_PUBLIC_KEY"})
    env = {"BV_LANGFUSE_SECRET_KEY": "sk-1", "BV_LANGFUSE_PUBLIC_KEY": "pk-1"}
    artifacts = tmp_path / "artifacts"
    assert prober_run_argv(spec, artifacts, "run-7", _WITNESS_IP, "opt-out", env) == [
        "docker",
        "run",
        "--rm",
        "--network",
        "bv-langfuse-internal",
        "--dns",
        _WITNESS_IP,
        "-v",
        f"{artifacts}:/experiment/artifacts",
        "-e",
        "BV_LANGFUSE_HOST=langfuse-web",
        "-e",
        "BV_LANGFUSE_PORT=3000",
        "-e",
        "BV_LANGFUSE_SECRET_KEY=sk-1",
        "-e",
        "BV_LANGFUSE_PUBLIC_KEY=pk-1",
        "bv-prober:run-7",
        "l1",
        "--backend",
        "langfuse",
        "--run-id",
        "run-7-airgap-opt-out",
    ]


# ------------------------------------------------------------------ dockerfile gate
def test_dockerfile_pinned_accepts_digest_and_names_violations(tmp_path: Path) -> None:
    pinned = tmp_path / "Dockerfile"
    pinned.write_text(f"FROM python:3.11-slim@sha256:{'a' * 64}\nCOPY . .\n", encoding="utf-8")
    assert dockerfile_pinned(pinned) == []
    todo = tmp_path / "Dockerfile.todo"
    todo.write_text("FROM python:3.11-slim@TODO_PIN\n", encoding="utf-8")
    violations = dockerfile_pinned(todo)
    assert violations and "not digest-pinned" in violations[0] and "pin-digests" in violations[0]
    empty = tmp_path / "Dockerfile.empty"
    empty.write_text("# nothing\n", encoding="utf-8")
    assert "no FROM line" in dockerfile_pinned(empty)[0]
    assert "unreadable" in dockerfile_pinned(tmp_path / "absent")[0]


def test_committed_prober_dockerfile_is_digest_pinned() -> None:
    # The shipped Dockerfile pins its FROM by digest (provenance in DIGESTS.md), so
    # the P4 gate accepts it; a reintroduced TODO_PIN would be refused (covered above).
    assert dockerfile_pinned(SUBTREE / "deploy" / "prober" / "Dockerfile") == []


# ------------------------------------------------------------------ overlay loader
def test_load_overlay_maps_reset_tag_to_sentinel(tmp_path: Path) -> None:
    path = tmp_path / "o.yaml"
    path.write_text("services:\n  web:\n    ports: !reset []\n", encoding="utf-8")
    data = load_overlay(path)
    assert data["services"]["web"]["ports"] is _RESET
    with pytest.raises(yaml.YAMLError):  # and this is exactly why safe_load cannot be used
        yaml.safe_load(path.read_text(encoding="utf-8"))
    scalar = tmp_path / "s.yaml"
    scalar.write_text("just a string\n", encoding="utf-8")
    assert load_overlay(scalar) == {}  # non-mapping top level degrades to empty


def test_load_overlay_constructs_override_tag_transparently(tmp_path: Path) -> None:
    # `!override <value>` REPLACES the base value at merge time (unlike `!reset`, which
    # drops it); for the static gate the value must read as itself on every node kind.
    path = tmp_path / "o.yaml"
    path.write_text(
        "services:\n"
        "  web:\n"
        "    networks: !override [bv-internal]\n"
        "    labels: !override {a: '1'}\n"
        "    user: !override root\n",
        encoding="utf-8",
    )
    web = load_overlay(path)["services"]["web"]
    assert web["networks"] == ["bv-internal"]
    assert web["labels"] == {"a": "1"}
    assert web["user"] == "root"


# ------------------------------------------------------------------ check_overlay
_BASE_TEXT = (
    f'name: bv-langfuse\nservices:\n  langfuse-web:\n    image: {_PINNED}\n    ports:\n      - "127.0.0.1:18321:3000"\n'
)


def _overlay_text(
    backend_id: str = "langfuse",
    service: str = "langfuse-web",
    *,
    internal: bool = True,
    named: bool = True,
    name_value: str | None = None,
    subnet: bool = True,
    enumerated: bool = True,
    joins_network: bool = True,
    reset_ports: bool = True,
    dns: bool = True,
    witness: bool = True,
    witness_static_ip: bool = True,
    witness_image: str = _WITNESS_PINNED,
    corefile_mount: str = "./Corefile:/etc/coredns/Corefile:ro",
) -> str:
    lines = ["networks:", "  bv-internal:"]
    if internal:
        lines.append("    internal: true")
    if named:
        lines.append(f"    name: {name_value or f'bv-{backend_id}-internal'}")
    if subnet:
        lines += ["    ipam:", "      config:", "        - subnet: 172.31.101.0/24"]
    lines.append("services:")
    if enumerated:
        lines.append(f"  {service}:")
        if joins_network:
            lines.append("    networks: [bv-internal]")
        lines.append("    ports: !reset []" if reset_ports else "    ports: []")
        if dns:
            lines.append(f"    dns: [{_WITNESS_IP}]")
    if witness:
        lines += [f"  {WITNESS_SERVICE}:", f"    image: {witness_image}"]
        if witness_static_ip:
            lines += ["    networks:", "      bv-internal:", f"        ipv4_address: {_WITNESS_IP}"]
        else:
            lines.append("    networks: [bv-internal]")
        if corefile_mount:
            lines += ["    volumes:", f"      - {corefile_mount}"]
    return "\n".join(lines) + "\n"


def _write_pair(tmp_path: Path, base_text: str, overlay_text: str) -> tuple[Path, Path, Path]:
    deploy_dir = tmp_path / "deploy" / "langfuse"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    base = deploy_dir / "compose.yaml"
    base.write_text(base_text, encoding="utf-8")
    overlay = deploy_dir / "compose.airgap.yaml"
    overlay.write_text(overlay_text, encoding="utf-8")
    return base, overlay, tmp_path


def test_check_overlay_accepts_a_compliant_overlay(tmp_path: Path) -> None:
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, _overlay_text())
    assert check_overlay(base, overlay, root) == []
    assert overlay_witness_ip(load_overlay(overlay)) == _WITNESS_IP


@pytest.mark.parametrize(
    ("overlay_kwargs", "needle"),
    [
        ({"internal": False}, "internal: true"),
        ({"named": False}, "explicit deterministic name"),
        ({"name_value": "bv-other-internal"}, "should be bv-langfuse-internal"),
        ({"subnet": False}, "ipam subnet"),
        ({"enumerated": False}, "not enumerated"),
        ({"joins_network": False}, "must join networks"),
        ({"reset_ports": False}, "!reset"),
        ({"dns": False}, "must set dns"),
        ({"witness": False}, "is missing"),
        ({"witness_static_ip": False}, "static ipv4_address"),
        ({"witness_image": "coredns/coredns:1.12.1@TODO_PIN"}, "digest-pinned"),
        ({"corefile_mount": "./Corefile:/etc/coredns/Corefile"}, "read-only"),
        ({"corefile_mount": ""}, "read-only"),
        ({"corefile_mount": "../../../etc/Corefile:/etc/coredns/Corefile:ro"}, "escapes the subtree"),
    ],
)
def test_check_overlay_violation_matrix(tmp_path: Path, overlay_kwargs: dict[str, object], needle: str) -> None:
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, _overlay_text(**overlay_kwargs))  # type: ignore[arg-type]
    violations = check_overlay(base, overlay, root)
    assert any(needle in violation for violation in violations), violations


def test_check_overlay_flags_every_unenumerated_base_service(tmp_path: Path) -> None:
    base_text = (
        "name: bv-langfuse\n"
        "services:\n"
        f"  langfuse-web:\n    image: {_PINNED}\n    ports: ['127.0.0.1:1:3000']\n"
        f"  postgres:\n    image: {_PINNED}\n"
    )
    base, overlay, root = _write_pair(tmp_path, base_text, _overlay_text())
    violations = check_overlay(base, overlay, root)
    assert any("'postgres' is not enumerated" in violation for violation in violations)
    assert not any("'langfuse-web' is not enumerated" in violation for violation in violations)


def test_check_overlay_accepts_override_networks_form(tmp_path: Path) -> None:
    # Services with EXPLICIT base networks (e.g. bv-judge-net attachments) must use
    # `networks: !override [bv-internal]` — a plain list would UNION with the base.
    # The gate reads the override's value and is satisfied by the bv-internal membership.
    overlay_text = _overlay_text().replace("    networks: [bv-internal]", "    networks: !override [bv-internal]", 1)
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, overlay_text)
    assert check_overlay(base, overlay, root) == []


def test_check_overlay_refuses_reset_on_networks(tmp_path: Path) -> None:
    # Empirically `!reset [value]` DROPS the value at merge time — a service "re-homed"
    # that way would end up on no explicit network at all. The gate must refuse it.
    overlay_text = _overlay_text().replace("    networks: [bv-internal]", "    networks: !reset [bv-internal]", 1)
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, overlay_text)
    violations = check_overlay(base, overlay, root)
    assert any("must join networks" in violation for violation in violations)


def test_check_overlay_accepts_long_form_readonly_corefile(tmp_path: Path) -> None:
    overlay_text = _overlay_text(corefile_mount="") + (
        "    volumes:\n      - {type: bind, source: ./Corefile, target: /Corefile, read_only: true}\n"
    )
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, overlay_text)
    assert check_overlay(base, overlay, root) == []


def test_check_overlay_mapping_networks_named_volumes_and_null_services(tmp_path: Path) -> None:
    # Mapping-form `networks:` satisfies membership; docker-managed named volumes are
    # exempt from containment; a null service entry is skipped without crashing.
    overlay_text = (
        "networks:\n"
        "  bv-internal:\n"
        "    internal: true\n"
        "    name: bv-langfuse-internal\n"
        "    ipam:\n"
        "      config:\n"
        "        - subnet: 172.31.101.0/24\n"
        "services:\n"
        "  langfuse-web:\n"
        "    networks:\n"
        "      bv-internal: {}\n"
        "    ports: !reset []\n"
        f"    dns: [{_WITNESS_IP}]\n"
        "    volumes:\n"
        "      - app-cache:/cache\n"
        "  stray: ~\n"
        f"  {WITNESS_SERVICE}:\n"
        f"    image: {_WITNESS_PINNED}\n"
        "    networks:\n"
        "      bv-internal:\n"
        f"        ipv4_address: {_WITNESS_IP}\n"
        "    volumes:\n"
        "      - ./Corefile:/etc/coredns/Corefile:ro\n"
    )
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, overlay_text)
    assert check_overlay(base, overlay, root) == []


def test_check_overlay_long_form_corefile_without_read_only_is_flagged(tmp_path: Path) -> None:
    overlay_text = _overlay_text(corefile_mount="") + (
        "    volumes:\n"
        "      - {type: bind, source: ./Corefile, target: /Corefile}\n"
        "      - {type: bind, source: ./zone.conf, target: /z, read_only: true}\n"
    )
    base, overlay, root = _write_pair(tmp_path, _BASE_TEXT, overlay_text)
    violations = check_overlay(base, overlay, root)
    assert any("read-only" in violation for violation in violations)


def test_check_overlay_reports_unreadable_or_malformed_files(tmp_path: Path) -> None:
    deploy_dir = tmp_path / "deploy" / "langfuse"
    deploy_dir.mkdir(parents=True)
    base = deploy_dir / "compose.yaml"
    overlay = deploy_dir / "compose.airgap.yaml"
    overlay.write_text(_overlay_text(), encoding="utf-8")
    assert "cannot read base compose" in check_overlay(base, overlay, tmp_path)[0]
    base.write_text("services: [unclosed\n", encoding="utf-8")
    assert "not valid YAML" in check_overlay(base, overlay, tmp_path)[0]
    base.write_text("- a list\n", encoding="utf-8")
    assert "must be a mapping" in check_overlay(base, overlay, tmp_path)[0]
    base.write_text(_BASE_TEXT, encoding="utf-8")
    assert "cannot read air-gap overlay" in check_overlay(base, deploy_dir / "absent.yaml", tmp_path)[0]
    bad_overlay = deploy_dir / "bad.yaml"
    bad_overlay.write_text("networks: [unclosed\n", encoding="utf-8")
    assert "not valid YAML" in check_overlay(base, bad_overlay, tmp_path)[0]
    empty_overlay = deploy_dir / "empty.yaml"
    empty_overlay.write_text("{}\n", encoding="utf-8")
    assert any("networks.bv-internal is missing" in v for v in check_overlay(base, empty_overlay, tmp_path))


# ------------------------------------------------------------------ iptables (B2)
class ScriptedRunner:
    def __init__(self, results: list[CompletedCommand]) -> None:
        self._results = list(results)
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
        self.calls.append(list(argv))
        return self._results.pop(0) if self._results else CompletedCommand(tuple(argv), 0)


def _ok(stdout: str) -> CompletedCommand:
    return CompletedCommand(("x",), 0, stdout=stdout)


def _fail() -> CompletedCommand:
    return CompletedCommand(("x",), 1, stderr="boom")


def test_iptables_reader_positive_identification_returns_count() -> None:
    leaky = _IPTABLES_CLEAN.replace(
        f"       0        0 DROP       all  --  {_BRIDGE} !", f"      42     3150 DROP       all  --  {_BRIDGE} !"
    )
    runner = ScriptedRunner([_ok(_NET_ID + "\n"), _ok(leaky)])
    assert read_iptables_egress_hits(runner, "bv-langfuse-internal") == 42
    assert runner.calls[0] == ["docker", "network", "inspect", "bv-langfuse-internal", "--format", "{{.Id}}"]
    assert runner.calls[1] == ["iptables", "-w", "-L", "-v", "-n", "-x"]


def test_iptables_reader_zero_counter_is_a_positive_zero() -> None:
    runner = ScriptedRunner([_ok(_NET_ID), _ok(_IPTABLES_CLEAN)])
    assert read_iptables_egress_hits(runner, "bv-langfuse-internal") == 0  # trustworthy zero, not a default


@pytest.mark.parametrize(
    "results",
    [
        [_fail()],  # docker network inspect fails
        [_ok("not-a-hex-id\n")],  # garbage network id
        [_ok(_NET_ID), _fail()],  # iptables command fails
        [_ok(_NET_ID), _ok("Chain FORWARD (policy ACCEPT)\n  pkts bytes target\n")],  # no matching rule
        [
            _ok(_NET_ID),
            _ok(
                _IPTABLES_CLEAN + f"       9        9 DROP       all  --  {_BRIDGE} !{_BRIDGE}  0.0.0.0/0  0.0.0.0/0\n"
            ),
        ],  # ambiguous duplicates
        [
            _ok(_NET_ID),
            _ok(f"     bad        0 DROP       all  --  {_BRIDGE} !{_BRIDGE}  0.0.0.0/0  0.0.0.0/0\n"),
        ],  # unparseable counter
    ],
)
def test_iptables_reader_returns_none_on_every_doubt(results: list[CompletedCommand]) -> None:
    # B2: any failure/ambiguity is None (-> recorded degraded observation), NEVER 0.
    assert read_iptables_egress_hits(ScriptedRunner(results), "bv-langfuse-internal") is None


# ------------------------------------------------------------------ log collectors
def test_collectors_return_output_or_empty_on_failure(tmp_path: Path) -> None:
    base, overlay = tmp_path / "b.yaml", tmp_path / "o.yaml"
    ok_runner = ScriptedRunner([CompletedCommand(("x",), 0, stdout="query-lines", stderr="warn")])
    assert collect_witness_log(ok_runner, base, overlay, "langfuse", {"K": "V"}) == "query-lines\nwarn"
    assert ok_runner.calls[0][-3:] == ["logs", "--no-color", WITNESS_SERVICE]
    failing = ScriptedRunner([_fail()])
    assert collect_witness_log(failing, base, overlay, "langfuse") == ""  # dead collection = dead witness
    all_runner = ScriptedRunner([CompletedCommand(("x",), 0, stdout="all-logs")])
    assert collect_container_logs(all_runner, base, overlay, "langfuse") == "all-logs"
    assert all_runner.calls[0][-2:] == ["logs", "--no-color"]
    assert collect_container_logs(ScriptedRunner([_fail()]), base, overlay, "langfuse") == ""


# ------------------------------------------------------------------ run_airgap flow
class FlowRunner:
    """Answers the whole P4 command flow by argv shape; records argv + env."""

    def __init__(
        self,
        *,
        docker_ok: bool = True,
        compose_ok: bool = True,
        build_rc: int = 0,
        up_rc: int = 0,
        canary_rc: int = 0,
        prober_rc: int = 0,
        normal_down_rc: int = 0,
        witness_logs: str | list[str] = _CANARY_WITNESS,
        container_logs: str = "",
        inspect_ok: bool = True,
        iptables_ok: bool = True,
        iptables_stdout: str = _IPTABLES_CLEAN,
    ) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[object] = []
        self._docker_ok = docker_ok
        self._compose_ok = compose_ok
        self._build_rc = build_rc
        self._up_rc = up_rc
        self._canary_rc = canary_rc
        self._prober_rc = prober_rc
        self._normal_down_rc = normal_down_rc
        self._witness_logs = witness_logs
        self._container_logs = container_logs
        self._inspect_ok = inspect_ok
        self._iptables_ok = iptables_ok
        self._iptables_stdout = iptables_stdout

    def _witness_log(self) -> str:
        if isinstance(self._witness_logs, list):
            return self._witness_logs.pop(0) if self._witness_logs else ""
        return self._witness_logs

    def run(self, argv: list[str], **kwargs: object) -> CompletedCommand:
        self.calls.append(list(argv))
        self.envs.append(kwargs.get("env"))
        if argv == ["docker", "--version"]:
            return CompletedCommand(
                tuple(argv), 0 if self._docker_ok else 127, stderr="" if self._docker_ok else "not found"
            )
        if argv == ["docker", "compose", "version"]:
            return CompletedCommand(
                tuple(argv), 0 if self._compose_ok else 1, stderr="" if self._compose_ok else "no compose"
            )
        if argv[:2] == ["docker", "build"]:
            return CompletedCommand(tuple(argv), self._build_rc, stderr="build blew up" if self._build_rc else "")
        if "--entrypoint" in argv:
            return CompletedCommand(tuple(argv), self._canary_rc)
        if argv[:2] == ["docker", "run"]:
            return CompletedCommand(tuple(argv), self._prober_rc, stdout="prober out", stderr="prober err")
        if "logs" in argv and argv[-1] == WITNESS_SERVICE:
            return CompletedCommand(tuple(argv), 0, stdout=self._witness_log())
        if "logs" in argv:
            return CompletedCommand(tuple(argv), 0, stdout=self._container_logs)
        if argv[:3] == ["docker", "network", "inspect"]:
            return CompletedCommand(
                tuple(argv), 0 if self._inspect_ok else 1, stdout=_NET_ID if self._inspect_ok else ""
            )
        if argv[0] == "iptables":
            return CompletedCommand(tuple(argv), 0 if self._iptables_ok else 4, stdout=self._iptables_stdout)
        if "up" in argv:
            return CompletedCommand(tuple(argv), self._up_rc, stderr="up failed" if self._up_rc else "")
        if "down" in argv and not any("-airgap" in part for part in argv):
            return CompletedCommand(tuple(argv), self._normal_down_rc)  # the NORMAL stack's teardown
        return CompletedCommand(tuple(argv), 0)


def _prep(tmp_subtree: Path, *, overlays: bool = True, pin_bases: bool = True, pin_dockerfile: bool = True) -> Settings:
    for backend, service, port in (("langfuse", "langfuse-web", "3000"), ("opik", "opik-frontend", "5173")):
        if pin_bases:
            (tmp_subtree / "deploy" / backend / "compose.yaml").write_text(
                f"name: bv-{backend}\n"
                "services:\n"
                f"  {service}:\n"
                f"    image: {_PINNED}\n"
                "    ports:\n"
                f'      - "127.0.0.1:1:{port}"\n',
                encoding="utf-8",
            )
        overlay_path = tmp_subtree / "deploy" / backend / "compose.airgap.yaml"
        if overlays:
            overlay_path.write_text(_overlay_text(backend, service), encoding="utf-8")
        else:
            # The committed tree ships real overlays (tmp_subtree copies them); the
            # missing-overlay scenario must remove them explicitly.
            overlay_path.unlink(missing_ok=True)
    if pin_dockerfile:
        (tmp_subtree / "deploy" / "prober" / "Dockerfile").write_text(
            f"FROM python:3.11-slim@sha256:{'a' * 64}\n", encoding="utf-8"
        )
    return load_settings(tmp_subtree / "config.yaml", env={})


def _io(runner: FlowRunner, **overrides: object) -> tuple[AirgapIO, list[float]]:
    sleeps: list[float] = []
    io = AirgapIO(runner=runner, sleeper=sleeps.append, now_fn=lambda: "2026-08-16T00:00:00+00:00", settle_seconds=1.5)
    for key, value in overrides.items():
        setattr(io, key, value)
    return io, sleeps


def test_run_airgap_unknown_backend_fails_before_touching_docker(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner()
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r", only_backend="mlflow")
    assert result.status == STATUS_FAIL and "not configured" in result.reason
    assert runner.calls == []


def test_run_airgap_blocks_without_docker_or_compose(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    result = run_airgap(tmp_subtree, settings, _io(FlowRunner(docker_ok=False))[0], env={}, run_id="r1")
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "docker is not available" in result.reason
    assert "docker is not available" in Path(result.artifacts[0]).read_text(encoding="utf-8")
    compose_less = run_airgap(tmp_subtree, settings, _io(FlowRunner(compose_ok=False))[0], env={}, run_id="r2")
    assert compose_less.status == STATUS_BLOCKED and "docker compose v2" in compose_less.reason


def test_run_airgap_blocks_on_missing_overlays_naming_every_backend(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree, overlays=False)
    runner = FlowRunner()
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "air-gap overlay missing for langfuse" in result.reason
    report = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert "overlay missing for langfuse" in report and "overlay missing for opik" in report
    assert not any("build" in argv for argv in runner.calls)  # gates block before any build


def test_committed_tree_passes_every_airgap_static_gate(tmp_subtree: Path) -> None:
    # The tree as committed: digest-pinned bases, real overlays, pinned prober FROM —
    # every static P4 gate must be clean, so a live `make airgap` reaches docker itself.
    settings = load_settings(tmp_subtree / "config.yaml", env={})
    for spec in settings.backends:
        base = tmp_subtree / spec.compose_file
        assert all(image.pinned for image in refuse_unpinned(base))
        overlay = overlay_path(tmp_subtree, spec)
        assert overlay.is_file()
        assert check_overlay(base, overlay, tmp_subtree) == []
    assert dockerfile_pinned(tmp_subtree / "deploy" / "prober" / "Dockerfile") == []


def test_run_airgap_blocks_on_overlay_violation(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    overlay = tmp_subtree / "deploy" / "opik" / "compose.airgap.yaml"
    overlay.write_text(_overlay_text("opik", "opik-frontend", reset_ports=False), encoding="utf-8")
    result = run_airgap(tmp_subtree, settings, _io(FlowRunner())[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "!reset" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_run_airgap_blocks_on_malformed_overlay_yaml(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    (tmp_subtree / "deploy" / "opik" / "compose.airgap.yaml").write_text("networks: [unclosed\n", encoding="utf-8")
    result = run_airgap(tmp_subtree, settings, _io(FlowRunner())[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "not valid YAML" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_gate_flags_backend_without_endpoint_row(tmp_path: Path) -> None:
    # A configured backend with no row in _IN_NETWORK_ENDPOINTS (e.g. a future mlflow)
    # must gate-BLOCK naming the missing row — never crash later in prober_env_pairs.
    deploy_dir = tmp_path / "deploy" / "mlflow"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "compose.yaml").write_text(_BASE_TEXT.replace("bv-langfuse", "bv-mlflow"), encoding="utf-8")
    (deploy_dir / "compose.airgap.yaml").write_text(_overlay_text("mlflow"), encoding="utf-8")
    violations, gate = _gate_backend(_spec("mlflow"), tmp_path)
    assert gate is None
    assert any("no in-network endpoint for backend 'mlflow'" in violation for violation in violations)


def test_run_airgap_proceeds_when_normal_stack_down_fails(tmp_subtree: Path) -> None:
    # A noisy teardown of the (possibly never-started) normal stack must not block the
    # observation — the air-gap `up` is the real gate.
    settings = _prep(tmp_subtree)
    result = run_airgap(
        tmp_subtree, settings, _io(FlowRunner(normal_down_rc=1))[0], env={}, run_id="r", only_backend="langfuse"
    )
    assert result.status == STATUS_OK, result.reason


def test_run_airgap_blocks_on_network_name_mismatch(tmp_subtree: Path) -> None:
    # The base name and the overlay name agree (bv-wrong) so check_overlay is content,
    # but the deterministic-name contract the docker-run builders rely on still gates.
    settings = _prep(tmp_subtree)
    base = tmp_subtree / "deploy" / "opik" / "compose.yaml"
    base.write_text(base.read_text(encoding="utf-8").replace("name: bv-opik", "name: bv-wrong"), encoding="utf-8")
    overlay = tmp_subtree / "deploy" / "opik" / "compose.airgap.yaml"
    overlay.write_text(_overlay_text("opik", "opik-frontend", name_value="bv-wrong-internal"), encoding="utf-8")
    result = run_airgap(tmp_subtree, settings, _io(FlowRunner())[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "'bv-wrong-internal' != 'bv-opik-internal'" in Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_run_airgap_blocks_when_prober_build_fails(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(build_rc=1)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "prober image build failed" in result.reason and "build blew up" in result.reason
    assert not any("down" in argv for argv in runner.calls)  # nothing was ever brought up


def test_run_airgap_up_failure_blocks_and_still_downs(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(up_rc=1)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED
    assert "compose up (air-gap overlay) failed" in result.reason
    airgap_downs = [argv for argv in runner.calls if "bv-langfuse-airgap" in argv and "down" in argv]
    assert airgap_downs and airgap_downs[0][-2:] == ["down", "-v"]  # the finally fired


def test_run_airgap_happy_dual_run_exact_sequence_and_evidence(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    env = {"BV_LANGFUSE_SECRET_KEY": "sk", "BV_LANGFUSE_PUBLIC_KEY": "pk"}
    runner = FlowRunner()
    io, sleeps = _io(runner)
    result = run_airgap(tmp_subtree, settings, io, env=env, run_id="run-9")
    assert result.status == STATUS_OK, result.reason
    assert result.exit_code == 0

    artifacts = tmp_subtree / "artifacts"
    expected: list[list[str]] = [
        ["docker", "--version"],
        ["docker", "compose", "version"],
        prober_build_argv(tmp_subtree, "run-9"),
    ]
    for backend in ("langfuse", "opik"):
        base = tmp_subtree / "deploy" / backend / "compose.yaml"
        overlay = tmp_subtree / "deploy" / backend / "compose.airgap.yaml"
        spec = settings.backend(backend)
        expected.append(["docker", "compose", "-f", str(base), "-p", f"bv-{backend}", "down", "-v"])
        for label in ("as-shipped", "opt-out"):
            expected += [
                airgap_compose_argv(base, overlay, backend, "up", "-d"),
                canary_run_argv(backend, "run-9", _WITNESS_IP),
                prober_run_argv(spec, artifacts, "run-9", _WITNESS_IP, label, env),
                airgap_compose_argv(base, overlay, backend, "logs", "--no-color", WITNESS_SERVICE),
                airgap_compose_argv(base, overlay, backend, "logs", "--no-color"),
                ["docker", "network", "inspect", f"bv-{backend}-internal", "--format", "{{.Id}}"],
                ["iptables", "-w", "-L", "-v", "-n", "-x"],
                airgap_compose_argv(base, overlay, backend, "down", "-v"),
            ]
    assert runner.calls == expected
    assert sleeps == [1.5, 1.5, 1.5, 1.5]  # settle once per observed run

    # The compose up env is the process env MERGED with the label's dual-scoring lever.
    lf_up_env_as_shipped = runner.envs[4]
    assert lf_up_env_as_shipped == {**env, "BV_LANGFUSE_TELEMETRY": "true"}
    lf_up_env_opt_out = runner.envs[12]
    assert lf_up_env_opt_out == {**env, "BV_LANGFUSE_TELEMETRY": "false"}

    verdicts_path = artifacts / "run-9" / "airgap" / "verdicts.json"
    assert str(verdicts_path) in result.artifacts
    payload = json.loads(verdicts_path.read_text(encoding="utf-8"))
    assert [entry["backend"] for entry in payload["verdicts"]] == ["langfuse", "opik"]
    assert all(entry["air_gapped_confirmed"] for entry in payload["verdicts"])
    report_body = (tmp_subtree / "reports" / "airgap_report.md").read_text(encoding="utf-8")
    assert "| langfuse |" in report_body and "| opik |" in report_body
    for label in ("as-shipped", "opt-out"):
        label_dir = artifacts / "run-9" / "airgap" / "langfuse" / label
        assert (label_dir / "witness.log").exists()
        assert (label_dir / "containers.log").exists()
        assert "returncode: 0" in (label_dir / "prober.log").read_text(encoding="utf-8")
        assert (label_dir / "canary.log").exists()


def test_run_airgap_canary_rc_is_ignored(tmp_subtree: Path) -> None:
    # B1: the canary's exit code is noise; only its DNS query line matters.
    settings = _prep(tmp_subtree)
    result = run_airgap(
        tmp_subtree, settings, _io(FlowRunner(canary_rc=1))[0], env={}, run_id="r", only_backend="langfuse"
    )
    assert result.status == STATUS_OK, result.reason


def test_run_airgap_prober_rc3_blocks_with_logs_as_evidence(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(prober_rc=3)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r")
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "prober exited rc=3" in result.reason
    prober_logs = [artifact for artifact in result.artifacts if artifact.endswith("prober.log")]
    assert prober_logs and "returncode: 3" in Path(prober_logs[0]).read_text(encoding="utf-8")
    airgap_downs = [argv for argv in runner.calls if "bv-langfuse-airgap" in argv and "down" in argv]
    assert airgap_downs  # the stack still came down


def test_run_airgap_prober_rc4_halts(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(prober_rc=4)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r")
    assert result.status == STATUS_HALT and result.exit_code == 4
    assert "HALTed (rc=4)" in result.reason
    report = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert "negative control PASSED inside the air-gapped re-run" in report
    airgap_downs = [argv for argv in runner.calls if "bv-langfuse-airgap" in argv and "down" in argv]
    assert airgap_downs  # teardown happens even on the HALT path


def test_run_airgap_dead_witness_blocks_unconfirmed(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(witness_logs="", iptables_ok=False)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r", only_backend="langfuse")
    assert result.status == STATUS_BLOCKED
    assert "cannot confirm OR deny" in result.reason
    verdicts_path = tmp_subtree / "artifacts" / "r" / "airgap" / "verdicts.json"
    assert verdicts_path.exists()  # the evidence still lands before the BLOCK
    payload = json.loads(verdicts_path.read_text(encoding="utf-8"))
    assert payload["verdicts"][0]["unconfirmed"] is True
    assert "unconfirmed" in (tmp_subtree / "reports" / "airgap_report.md").read_text(encoding="utf-8")


def test_run_airgap_detected_egress_is_ok_with_unconfirmed_claim(tmp_subtree: Path) -> None:
    # Egress on BOTH runs: honest evidence, not a phase failure — the matrix's Yes is
    # simply not confirmed.
    settings = _prep(tmp_subtree)
    runner = FlowRunner(witness_logs=_LEAKY_WITNESS)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r", only_backend="langfuse")
    assert result.status == STATUS_OK
    assert "egress persists after opt-out (evidence, not failure)" in result.reason
    payload = json.loads((tmp_subtree / "artifacts" / "r" / "airgap" / "verdicts.json").read_text(encoding="utf-8"))
    verdict = payload["verdicts"][0]
    assert verdict["air_gapped_confirmed"] is False and verdict["unconfirmed"] is False
    assert "stats.comet.com" in verdict["as_shipped"]["observation"]["attempted_domains"]
    assert "no (egress detected)" in (tmp_subtree / "reports" / "airgap_report.md").read_text(encoding="utf-8")


def test_run_airgap_as_shipped_leak_with_clean_opt_out_confirms(tmp_subtree: Path) -> None:
    settings = _prep(tmp_subtree)
    runner = FlowRunner(witness_logs=[_LEAKY_WITNESS, _CANARY_WITNESS])
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r", only_backend="langfuse")
    assert result.status == STATUS_OK
    assert "air-gapped after opt-out (as-shipped egress recorded)" in result.reason


def test_run_airgap_iptables_none_degrades_to_witness_only(tmp_subtree: Path) -> None:
    # inspect failing -> reader None -> observe_egress(iptables_available=False): the
    # live canary witness still supports the verdict, but the observation is degraded.
    settings = _prep(tmp_subtree)
    runner = FlowRunner(inspect_ok=False)
    result = run_airgap(tmp_subtree, settings, _io(runner)[0], env={}, run_id="r", only_backend="langfuse")
    assert result.status == STATUS_OK, result.reason
    payload = json.loads((tmp_subtree / "artifacts" / "r" / "airgap" / "verdicts.json").read_text(encoding="utf-8"))
    observation = payload["verdicts"][0]["opt_out"]["observation"]
    assert observation["mechanism"] == "dns-witness" and observation["degraded"] is True
    assert "iptables unavailable" in observation["notes"]


def test_run_airgap_scoped_rerun_merges_verdicts_instead_of_overwriting(tmp_subtree: Path) -> None:
    # A --backend re-run under the same run id refreshes that backend's verdict only;
    # the other backend's persisted P4 evidence must survive (evidence-loss regression).
    settings = _prep(tmp_subtree)
    first = run_airgap(tmp_subtree, settings, _io(FlowRunner())[0], env={}, run_id="r", only_backend="langfuse")
    assert first.status == STATUS_OK
    second = run_airgap(tmp_subtree, settings, _io(FlowRunner())[0], env={}, run_id="r", only_backend="opik")
    assert second.status == STATUS_OK
    payload = json.loads((tmp_subtree / "artifacts" / "r" / "airgap" / "verdicts.json").read_text(encoding="utf-8"))
    assert [entry["backend"] for entry in payload["verdicts"]] == ["langfuse", "opik"]
    report = (tmp_subtree / "reports" / "airgap_report.md").read_text(encoding="utf-8")
    assert "langfuse" in report and "opik" in report  # re-render covers the merged set


def test_dockerfile_pinned_accepts_multistage_stage_references(tmp_path: Path) -> None:
    # `FROM <stage>` names an earlier build stage, not a registry image — the digest
    # gate must not demand a sha256 for it.
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM python:3.11-slim@sha256:{'a' * 64} AS base\nFROM base\nCOPY . .\n",
        encoding="utf-8",
    )
    assert dockerfile_pinned(dockerfile) == []
    # A genuinely unpinned image ref after a stage line is still refused.
    dockerfile.write_text(
        f"FROM python:3.11-slim@sha256:{'a' * 64} AS base\nFROM ubuntu:24.04\n",
        encoding="utf-8",
    )
    violations = dockerfile_pinned(dockerfile)
    assert violations and "ubuntu:24.04" in violations[0]
