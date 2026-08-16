"""P4 air-gap orchestration: egress-blocked L1 re-runs, dual-scored, or BLOCKED.

Kept separate from ``phases.py`` (which owns P0/P2) for the 500-line file budget; it
shares the ``PhaseResult``/BLOCKED-report vocabulary. The mechanism, and WHY each piece
exists:

- The stacks are recreated on an ``internal: true`` network from a committed overlay; a
  CoreDNS witness sidecar logs every lookup. Published ports die on internal networks, so
  the L1 suite re-runs from an in-network prober container built during this phase.
- **Canary (peer review B1):** docker's embedded DNS answers service names locally, so a
  clean run leaves the witness log EMPTY — indistinguishable from a dead sidecar. One
  ``getaddrinfo`` for ``CANARY_DOMAIN`` before the prober proves the witness captures
  (its return code is deliberately ignored: the DNS query line is the point).
- **iptables (peer review B2):** ``read_iptables_egress_hits`` returns an int ONLY on
  positively identifying THIS run's bridge DROP counter; every doubt returns ``None``,
  which flows into ``observe_egress``'s degraded witness-only path. Never a guessed zero.
- **Prober exit codes (peer review M4):** rc=4 (a negative control passed inside the
  air-gapped re-run) HALTs the whole phase; any other nonzero rc makes the observation
  non-usable -> BLOCKED with the logs as evidence. A blocked probe run must never still
  confirm an air gap.

Everything docker-shaped goes through the injected ``CommandRunner`` so every branch is
unit-testable offline with scripted runners.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from backend_validation.airgap import (
    CANARY_DOMAIN,
    AirgapVerdict,
    EgressObservation,
    dual_score,
    observe_egress,
)
from backend_validation.deploy import (
    _DIGEST_RE,
    _FROM_LINE,
    _NAMED_VOLUME,
    DeployError,
    down_stack,
    refuse_unpinned,
)
from backend_validation.logging_util import get_logger
from backend_validation.phases import (
    EXIT_BY_STATUS,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_HALT,
    STATUS_OK,
    PhaseResult,
    write_blocked_report,
)
from backend_validation.procrun import CommandRunner, CompletedCommand
from backend_validation.report import render_airgap_report, write_report
from backend_validation.runner import utc_now_iso
from backend_validation.settings import BackendSpec, Settings

logger = get_logger(__name__)

WITNESS_SERVICE = "bv-dns-witness"
OVERLAY_NETWORK_KEY = "bv-internal"  # the overlay's top-level networks key
_PROBER_HALT_RC = EXIT_BY_STATUS[STATUS_HALT]  # the CLI contract the in-container run obeys

_PROBE_TIMEOUT = 30.0
_BUILD_TIMEOUT = 1800.0
_UP_TIMEOUT = 1800.0
_CANARY_TIMEOUT = 120.0
_PROBER_TIMEOUT = 3600.0  # a full L1 re-run with retries; generous beats a fake timeout-BLOCK
_LOGS_TIMEOUT = 120.0
_DOWN_TIMEOUT = 600.0
_IPTABLES_TIMEOUT = 60.0

# Compose override tags: `!reset` DELETES an inherited key at merge time (and empirically
# drops any value written next to it), while `!override <value>` REPLACES the inherited
# value wholesale. yaml.safe_load raises ConstructorError on both, so overlays are parsed
# ONLY with this Safe-derived loader. `!reset` maps to a sentinel so `check_overlay` can
# statically assert the tag is present on port publishers (peer review M1: a plain
# `ports: []` is a merge NO-OP and must be refused); `!override` constructs transparently
# so `networks: !override [bv-internal]` — required where the base declares explicit
# networks (e.g. bv-judge-net), which a plain list would merely UNION with — reads as the
# list it replaces the base value with.
_RESET: object = object()


class _OverlayLoader(yaml.SafeLoader):
    """SafeLoader that understands compose's ``!reset``/``!override`` tags (still safe)."""


def _construct_reset(_loader: yaml.SafeLoader, _node: yaml.Node) -> object:
    return _RESET


def _construct_override(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(cast("yaml.ScalarNode", node))  # the only node kind left


_OverlayLoader.add_constructor("!reset", _construct_reset)
_OverlayLoader.add_constructor("!override", _construct_override)


def load_overlay(overlay_path_: Path) -> dict[str, Any]:
    """Parse an air-gap overlay with the ``!reset``-aware safe loader."""
    data = yaml.load(overlay_path_.read_text(encoding="utf-8"), Loader=_OverlayLoader)  # Safe-derived loader
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class _InNetworkEndpoint:
    """Where the prober reaches a backend FROM INSIDE the compose network: the compose
    service name (docker DNS answers it) and the CONTAINER port — published host ports
    are dead on internal networks (peer review M3)."""

    service: str
    port: str
    passes_workspace: bool = False  # opik: config.yaml interpolates ${BV_OPIK_WORKSPACE}


_IN_NETWORK_ENDPOINTS: dict[str, _InNetworkEndpoint] = {
    "langfuse": _InNetworkEndpoint("langfuse-web", "3000"),
    "opik": _InNetworkEndpoint("opik-frontend", "5173", passes_workspace=True),
}


class ProberHaltError(RuntimeError):
    """The in-network prober exited 4: a negative control passed air-gapped -> HALT."""

    def __init__(self, message: str, artifacts: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.artifacts = artifacts


class AirgapObservationError(RuntimeError):
    """An observation could not be collected usably (up failed, prober rc != 0)."""

    def __init__(self, message: str, artifacts: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.artifacts = artifacts


# ------------------------------------------------------------------ iptables (B2)
def read_iptables_egress_hits(runner: CommandRunner, network_id: str) -> int | None:
    """Packet count of THIS run's internal-bridge egress DROP rule, or ``None``.

    The B2 contract: an int is returned ONLY when the counter is positively identified —
    the network resolves to a 64-hex id, the ``iptables`` listing succeeds, and exactly
    one DROP rule matches ``in=br-<id[:12]> out=!br-<id[:12]>``. Command failure, no
    match, ambiguity, or unparseable output all return ``None``, which the caller maps to
    ``observe_egress(iptables_available=False)`` (the recorded-degradation path). A
    defaulted 0 here would forge a trustworthy-zero egress claim; that is the one thing
    this function must never do.

    ``network_id`` is the name-or-id handed to ``docker network inspect`` — the
    orchestrator passes the deterministic ``bv-<backend>-internal`` overlay network name.
    """
    inspect = runner.run(["docker", "network", "inspect", network_id, "--format", "{{.Id}}"], timeout=_IPTABLES_TIMEOUT)
    if not inspect.ok:
        return None
    full_id = inspect.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", full_id):
        return None  # ambiguous/garbage inspect output — never guess a bridge name
    bridge = f"br-{full_id[:12]}"
    listing = runner.run(["iptables", "-w", "-L", "-v", "-n", "-x"], timeout=_IPTABLES_TIMEOUT)
    if not listing.ok:
        return None
    counts: list[int] = []
    for line in listing.stdout.splitlines():
        tokens = line.split()
        # `-L -v -n -x` data rows: pkts bytes target prot opt in out source destination.
        if len(tokens) < 7 or tokens[2] != "DROP":
            continue
        if tokens[5] == bridge and tokens[6] == f"!{bridge}":
            try:
                counts.append(int(tokens[0]))
            except ValueError:
                return None  # a counter we cannot read is a counter we do not have
    if len(counts) != 1:
        return None  # no match (layout drift?) or ambiguous duplicates — degrade honestly
    return counts[0]


@dataclass
class AirgapIO:
    """Injectable environment edges for P4, mirroring ``PhaseIO``'s discipline."""

    runner: CommandRunner
    sleeper: Callable[[float], None] = time.sleep
    now_fn: Callable[[], str] = utc_now_iso
    settle_seconds: float = 60.0  # post-up quiet period so background telemetry gets its chance
    iptables_reader: Callable[[CommandRunner, str], int | None] = read_iptables_egress_hits


# ------------------------------------------------------------------ pure builders
def airgap_project_name(backend_id: str) -> str:
    """Distinct compose project so airgap volumes/containers never collide with P1's."""
    return f"bv-{backend_id}-airgap"


def internal_network_name(backend_id: str) -> str:
    """The overlay declares this exact name so ``docker run --network`` never depends on
    compose project-name mangling."""
    return f"bv-{backend_id}-internal"


def overlay_path(subtree_root: Path, spec: BackendSpec) -> Path:
    """``deploy/<backend>/compose.airgap.yaml``, next to the backend's base compose."""
    return (subtree_root / spec.compose_file).parent / "compose.airgap.yaml"


def airgap_compose_argv(base: Path, overlay: Path, backend_id: str, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(base),
        "-f",
        str(overlay),
        "-p",
        airgap_project_name(backend_id),
        *args,
    ]


def prober_image(run_id: str) -> str:
    return f"bv-prober:{run_id}"


def prober_build_argv(subtree_root: Path, run_id: str) -> list[str]:
    return [
        "docker",
        "build",
        "-f",
        str(subtree_root / "deploy" / "prober" / "Dockerfile"),
        "-t",
        prober_image(run_id),
        str(subtree_root),
    ]


# The canary body: one lookup for the reserved-TLD canary domain, exceptions swallowed
# (the witness answers NXDOMAIN by design — the logged query line is the entire point).
_CANARY_SNIPPET = (
    f"import socket, contextlib\nwith contextlib.suppress(OSError): socket.getaddrinfo({CANARY_DOMAIN!r}, 53)\n"
)


def canary_run_argv(backend_id: str, run_id: str, witness_ip: str) -> list[str]:
    """B1 witness-liveness canary; the runner's return code is deliberately ignored."""
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        internal_network_name(backend_id),
        "--dns",
        witness_ip,
        "--entrypoint",
        "python",
        prober_image(run_id),
        "-c",
        _CANARY_SNIPPET,
    ]


def _env_prefix(backend_id: str) -> str:
    return f"BV_{backend_id.upper().replace('-', '_')}"


def prober_env_pairs(spec: BackendSpec, env: Mapping[str, str]) -> list[tuple[str, str]]:
    """The exact ``-e`` set for the in-network prober (peer review M3).

    Credential env NAMES come from ``spec.credential_env`` (never hardcoded beyond the
    endpoint table) and are passed through only when present in the process env: a
    missing credential surfaces as the prober's OWN BLOCKED (rc=3) — honest evidence —
    not a KeyError here.
    """
    endpoint = _IN_NETWORK_ENDPOINTS[spec.id]
    prefix = _env_prefix(spec.id)
    pairs = [(f"{prefix}_HOST", endpoint.service), (f"{prefix}_PORT", endpoint.port)]
    if endpoint.passes_workspace:
        pairs.append((f"{prefix}_WORKSPACE", spec.workspace))
    for env_name in spec.credential_env.values():  # declared (config.yaml) order
        if env_name in env:
            pairs.append((env_name, env[env_name]))
    return pairs


def prober_run_argv(
    spec: BackendSpec,
    artifacts_dir: Path,
    run_id: str,
    witness_ip: str,
    label: str,
    env: Mapping[str, str],
) -> list[str]:
    """The prober's L1 re-run: in-network, witness-DNS'd, artifacts bind-mounted."""
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        internal_network_name(spec.id),
        "--dns",
        witness_ip,
        "-v",
        f"{artifacts_dir}:/experiment/artifacts",
    ]
    for name, value in prober_env_pairs(spec, env):
        argv.extend(["-e", f"{name}={value}"])
    argv.extend([prober_image(run_id), "l1", "--backend", spec.id, "--run-id", f"{run_id}-airgap-{label}"])
    return argv


def dockerfile_pinned(dockerfile_path: Path) -> list[str]:
    """Digest gate for the prober Dockerfile: every FROM must carry ``@sha256:<64hex>``.

    Returns violation strings (``TODO_PIN`` and bare tags both violate) so the phase can
    name every finding in one BLOCKED report, mirroring ``refuse_unpinned``.
    """
    try:
        text = dockerfile_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"prober Dockerfile unreadable at {dockerfile_path.as_posix()}: {exc}"]
    refs: list[str] = []
    stages: set[str] = set()  # earlier `FROM ... AS <name>` stages are refs, not images
    for line in text.splitlines():
        match = _FROM_LINE.match(line.strip())
        if not match:
            continue
        if match.group("ref").lower() not in stages:
            refs.append(match.group("ref"))
        suffix = match.group("suffix")
        if suffix:
            stages.add(suffix.split()[-1].lower())
    if not refs:
        return [f"{dockerfile_path.name}: no FROM line found — not a buildable Dockerfile"]
    return [
        f"{dockerfile_path.name}: FROM {ref} is not digest-pinned (@sha256:<64hex>) — run `make pin-digests`"
        for ref in refs
        if not _DIGEST_RE.search(ref)
    ]


# ------------------------------------------------------------------ overlay gate
def overlay_witness_ip(overlay_data: Mapping[str, Any]) -> str | None:
    """The witness's declared static ip (app ``dns:`` entries and the canary dial it)."""
    services = overlay_data.get("services")
    witness = services.get(WITNESS_SERVICE) if isinstance(services, dict) else None
    networks = witness.get("networks") if isinstance(witness, dict) else None
    net = networks.get(OVERLAY_NETWORK_KEY) if isinstance(networks, dict) else None
    ip = net.get("ipv4_address") if isinstance(net, dict) else None
    return str(ip) if ip else None


def _overlay_network_name(overlay_data: Mapping[str, Any]) -> str | None:
    networks = overlay_data.get("networks")
    net = networks.get(OVERLAY_NETWORK_KEY) if isinstance(networks, dict) else None
    name = net.get("name") if isinstance(net, dict) else None
    return str(name) if isinstance(name, str) and name else None


def _networks_include(networks: object) -> bool:
    if isinstance(networks, list):
        return OVERLAY_NETWORK_KEY in [str(entry) for entry in networks]
    if isinstance(networks, dict):
        return OVERLAY_NETWORK_KEY in networks
    return False


def _dns_points_at(dns: object, witness_ip: str) -> bool:
    return isinstance(dns, list) and witness_ip in [str(entry) for entry in dns]


def _has_ro_corefile_mount(witness: Mapping[str, Any]) -> bool:
    for volume in witness.get("volumes") or []:
        if isinstance(volume, str):
            parts = volume.split(":")
            if len(parts) >= 3 and Path(parts[0]).name == "Corefile" and "ro" in parts[-1].split(","):
                return True
        elif isinstance(volume, dict) and Path(str(volume.get("source", ""))).name == "Corefile":
            if volume.get("read_only") is True:
                return True
    return False


def _network_violations(overlay_data: Mapping[str, Any], base_data: Mapping[str, Any], name: str) -> list[str]:
    networks = overlay_data.get("networks")
    net = networks.get(OVERLAY_NETWORK_KEY) if isinstance(networks, dict) else None
    if not isinstance(net, dict):
        return [f"{name}: top-level networks.{OVERLAY_NETWORK_KEY} is missing — the air-gap runs on that network"]
    violations: list[str] = []
    if net.get("internal") is not True:
        violations.append(f"{name}: networks.{OVERLAY_NETWORK_KEY} must set internal: true (that IS the egress block)")
    declared = net.get("name")
    base_name = base_data.get("name")
    if not isinstance(declared, str) or not declared:
        violations.append(
            f"{name}: networks.{OVERLAY_NETWORK_KEY} needs an explicit deterministic name "
            "(bv-<backend>-internal) — `docker run --network` must not depend on project-name mangling"
        )
    elif isinstance(base_name, str) and base_name and declared != f"{base_name}-internal":
        violations.append(f"{name}: networks.{OVERLAY_NETWORK_KEY}.name {declared!r} should be {base_name}-internal")
    ipam = net.get("ipam")
    configs = ipam.get("config") if isinstance(ipam, dict) else None
    subnets = [cfg.get("subnet") for cfg in configs if isinstance(cfg, dict)] if isinstance(configs, list) else []
    if not any(subnets):
        violations.append(
            f"{name}: networks.{OVERLAY_NETWORK_KEY} needs an ipam subnet (the witness's static ip must be predictable)"
        )
    return violations


def _witness_violations(overlay_services: Mapping[str, Any], witness_ip: str | None, name: str) -> list[str]:
    witness = overlay_services.get(WITNESS_SERVICE)
    if not isinstance(witness, dict):
        return [f"{name}: witness service {WITNESS_SERVICE!r} is missing — without it there is no egress observation"]
    violations: list[str] = []
    if witness_ip is None:
        violations.append(
            f"{name}: witness needs a static ipv4_address under networks.{OVERLAY_NETWORK_KEY} "
            "(app dns: entries and the canary point at it)"
        )
    if not _has_ro_corefile_mount(witness):
        violations.append(f"{name}: witness must mount a Corefile read-only (e.g. ../witness/Corefile:/Corefile:ro)")
    return violations


def _mount_violations(service: Mapping[str, Any], service_name: str, overlay: Path, subtree_root: Path) -> list[str]:
    """Zero-writes containment for overlay bind mounts (same law as the base composes)."""
    violations: list[str] = []
    root = subtree_root.resolve()
    for volume in service.get("volumes") or []:
        source = volume.split(":", 1)[0] if isinstance(volume, str) else str((volume or {}).get("source", ""))
        if _NAMED_VOLUME.fullmatch(source):
            continue
        if not (overlay.parent / source).resolve().is_relative_to(root):
            violations.append(f"{overlay.name}:{service_name}: bind mount {source} escapes the subtree")
    return violations


def check_overlay(base_path: Path, overlay_path_: Path, subtree_root: Path) -> list[str]:
    """Static air-gap overlay gate. Returns every violation (empty means compliant).

    The enforced contract: a top-level ``networks.bv-internal`` with ``internal: true``,
    an explicit deterministic ``name`` (``<base compose name>-internal``) and an ipam
    subnet; EVERY base-compose service enumerated with ``networks: [bv-internal]`` (else
    the implicit default network keeps it internet-attached); every base port-publishing
    service carrying ``ports: !reset []`` (M1: a plain ``[]`` is a merge no-op and
    engine behavior for published ports on internal networks is version-sensitive);
    every non-witness service pointing ``dns:`` at the witness's static ip; a
    ``bv-dns-witness`` service with a digest-pinned image, a read-only Corefile mount,
    and a static ``ipv4_address``; every image-bearing overlay service digest-pinned
    (the base file's digest law lives in ``refuse_unpinned`` — overlay partial services
    carry no ``image:``); and every overlay bind mount contained in the subtree.
    """
    try:
        base_data = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"cannot read base compose {base_path.as_posix()}: {exc}"]
    except yaml.YAMLError as exc:
        return [f"base compose {base_path.as_posix()} is not valid YAML: {exc}"]
    try:
        overlay_data = load_overlay(overlay_path_)
    except OSError as exc:
        return [f"cannot read air-gap overlay {overlay_path_.as_posix()}: {exc}"]
    except yaml.YAMLError as exc:
        return [f"air-gap overlay {overlay_path_.as_posix()} is not valid YAML: {exc}"]
    if not isinstance(base_data, dict):
        return [f"base compose {base_path.as_posix()} must be a mapping"]
    name = overlay_path_.name
    violations = _network_violations(overlay_data, base_data, name)
    witness_ip = overlay_witness_ip(overlay_data)
    raw_base_services = base_data.get("services")
    base_services: dict[str, Any] = raw_base_services if isinstance(raw_base_services, dict) else {}
    raw_overlay_services = overlay_data.get("services")
    overlay_services: dict[str, Any] = raw_overlay_services if isinstance(raw_overlay_services, dict) else {}
    violations.extend(_enumeration_violations(base_services, overlay_services, name))
    violations.extend(_witness_violations(overlay_services, witness_ip, name))
    violations.extend(_overlay_service_violations(overlay_services, witness_ip, overlay_path_, subtree_root))
    return violations


def _enumeration_violations(
    base_services: Mapping[str, Any], overlay_services: Mapping[str, Any], name: str
) -> list[str]:
    """Every base service re-homed onto the internal network; every publisher `!reset`."""
    violations: list[str] = []
    for service_name, base_service in sorted(base_services.items()):
        overlay_service = overlay_services.get(service_name)
        if not isinstance(overlay_service, dict):
            violations.append(
                f"{name}: base service {service_name!r} is not enumerated — it would keep the implicit "
                "default (non-internal) network attached"
            )
            continue
        if not _networks_include(overlay_service.get("networks")):
            violations.append(f"{name}: service {service_name!r} must join networks: [{OVERLAY_NETWORK_KEY}]")
        if isinstance(base_service, dict) and base_service.get("ports") and overlay_service.get("ports") is not _RESET:
            violations.append(
                f"{name}: service {service_name!r} publishes ports in the base file and must carry "
                "`ports: !reset []` (a plain [] is a merge no-op)"
            )
    return violations


def _overlay_service_violations(
    overlay_services: Mapping[str, Any], witness_ip: str | None, overlay_path_: Path, subtree_root: Path
) -> list[str]:
    """Per-overlay-service law: pinned images, witness-pointed dns, contained mounts."""
    name = overlay_path_.name
    violations: list[str] = []
    for service_name, overlay_service in sorted(overlay_services.items()):
        if not isinstance(overlay_service, dict):
            continue
        image = overlay_service.get("image")
        if image is not None and not (isinstance(image, str) and _DIGEST_RE.search(image)):
            violations.append(
                f"{name}: service {service_name!r} image {image!r} must be digest-pinned "
                "(@sha256:<64hex>) — run `make pin-digests`"
            )
        if (
            service_name != WITNESS_SERVICE
            and witness_ip is not None
            and not _dns_points_at(overlay_service.get("dns"), witness_ip)
        ):
            violations.append(
                f"{name}: service {service_name!r} must set dns: [{witness_ip}] so every lookup hits the witness"
            )
        violations.extend(_mount_violations(overlay_service, service_name, overlay_path_, subtree_root))
    return violations


# ------------------------------------------------------------------ log collection
def collect_witness_log(
    runner: CommandRunner, base: Path, overlay: Path, backend_id: str, env: Mapping[str, str] | None = None
) -> str:
    """The witness's query log; a failed collection reads as an EMPTY (unusable) log —
    absence of evidence must never become evidence of absence."""
    result = runner.run(
        airgap_compose_argv(base, overlay, backend_id, "logs", "--no-color", WITNESS_SERVICE),
        env=dict(env) if env is not None else None,
        timeout=_LOGS_TIMEOUT,
    )
    return "\n".join(part for part in (result.stdout, result.stderr) if part) if result.ok else ""


def collect_container_logs(
    runner: CommandRunner, base: Path, overlay: Path, backend_id: str, env: Mapping[str, str] | None = None
) -> str:
    result = runner.run(
        airgap_compose_argv(base, overlay, backend_id, "logs", "--no-color"),
        env=dict(env) if env is not None else None,
        timeout=_LOGS_TIMEOUT,
    )
    return "\n".join(part for part in (result.stdout, result.stderr) if part) if result.ok else ""


def _command_evidence(result: CompletedCommand) -> str:
    return (
        f"argv: {' '.join(result.argv)}\n"
        f"returncode: {result.returncode} (timed_out={result.timed_out})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
    )


# ------------------------------------------------------------------ orchestration
@dataclass(frozen=True)
class _GatedBackend:
    """One backend that passed every static gate, with everything the run needs."""

    spec: BackendSpec
    base: Path
    overlay: Path
    witness_ip: str


def _gate_backend(spec: BackendSpec, subtree_root: Path) -> tuple[list[str], _GatedBackend | None]:
    violations: list[str] = []
    base = subtree_root / spec.compose_file
    try:
        # Base file only: overlay partial services carry no image:, so compose_images
        # would crash there — overlay digest law lives inside check_overlay.
        refuse_unpinned(base)
    except DeployError as exc:
        violations.append(str(exc))
    overlay = overlay_path(subtree_root, spec)
    if not overlay.exists():
        violations.append(
            f"air-gap overlay missing for {spec.id}: {overlay} — commit deploy/{spec.id}/compose.airgap.yaml "
            "(internal network + witness + port resets) before any P4 run"
        )
        return violations, None
    violations.extend(check_overlay(base, overlay, subtree_root))
    if spec.id not in _IN_NETWORK_ENDPOINTS:
        violations.append(
            f"no in-network endpoint for backend {spec.id!r} — add its compose service/container-port "
            "row to airgap_phase._IN_NETWORK_ENDPOINTS"
        )
    witness_ip: str | None = None
    try:
        overlay_data = load_overlay(overlay)
    except (OSError, yaml.YAMLError):
        overlay_data = None  # already reported as a violation by check_overlay
    if overlay_data is not None:
        witness_ip = overlay_witness_ip(overlay_data)
        declared = _overlay_network_name(overlay_data)
        expected = internal_network_name(spec.id)
        if declared is not None and declared != expected:
            violations.append(
                f"{overlay.name}: networks.{OVERLAY_NETWORK_KEY}.name {declared!r} != {expected!r} — the "
                "canary/prober `docker run --network` argv depends on the deterministic name"
            )
    if witness_ip is None or violations:
        # witness_ip None always co-occurs with a check_overlay violation, so a backend is
        # never silently skipped: run_airgap BLOCKs on the collected violations.
        return violations, None
    return violations, _GatedBackend(spec=spec, base=base, overlay=overlay, witness_ip=witness_ip)


def _observe_factory(
    io: AirgapIO,
    env: Mapping[str, str],
    run_id: str,
    gate: _GatedBackend,
    artifacts_dir: Path,
) -> Callable[[str, dict[str, str]], EgressObservation]:
    """Build the per-label observation closure ``dual_score`` drives twice."""
    spec, base, overlay, witness_ip = gate.spec, gate.base, gate.overlay, gate.witness_ip
    backend_id = spec.id

    def observe(label: str, label_env: dict[str, str]) -> EgressObservation:
        label_dir = artifacts_dir / run_id / "airgap" / backend_id / label
        label_dir.mkdir(parents=True, exist_ok=True)
        merged_env = dict(env) | dict(label_env)
        try:
            up = io.runner.run(
                airgap_compose_argv(base, overlay, backend_id, "up", "-d"), env=merged_env, timeout=_UP_TIMEOUT
            )
            if not up.ok:
                raise AirgapObservationError(
                    f"[{backend_id}/{label}] compose up (air-gap overlay) failed (rc={up.returncode}, "
                    f"timed_out={up.timed_out}): {(up.stderr or up.stdout).strip()[:400]}"
                )
            io.sleeper(io.settle_seconds)
            # B1 canary: return code deliberately ignored — the witness-logged query is the point.
            canary = io.runner.run(canary_run_argv(backend_id, run_id, witness_ip), timeout=_CANARY_TIMEOUT)
            (label_dir / "canary.log").write_text(_command_evidence(canary), encoding="utf-8")
            prober = io.runner.run(
                prober_run_argv(spec, artifacts_dir, run_id, witness_ip, label, env), timeout=_PROBER_TIMEOUT
            )
            prober_log = label_dir / "prober.log"
            prober_log.write_text(_command_evidence(prober), encoding="utf-8")
            witness_log = collect_witness_log(io.runner, base, overlay, backend_id, merged_env)
            container_logs = collect_container_logs(io.runner, base, overlay, backend_id, merged_env)
            witness_path = label_dir / "witness.log"
            witness_path.write_text(witness_log, encoding="utf-8")
            containers_path = label_dir / "containers.log"
            containers_path.write_text(container_logs, encoding="utf-8")
            evidence = (str(prober_log), str(witness_path), str(containers_path))
            if prober.returncode == _PROBER_HALT_RC:
                # M4: a negative control passed INSIDE the egress-blocked re-run.
                raise ProberHaltError(
                    f"[{backend_id}/{label}] prober HALTed (rc={_PROBER_HALT_RC}): a negative control "
                    "passed inside the air-gapped re-run",
                    artifacts=evidence,
                )
            if not prober.ok:
                raise AirgapObservationError(
                    f"[{backend_id}/{label}] prober exited rc={prober.returncode} "
                    f"(timed_out={prober.timed_out}); a blocked/failed probe run can never confirm an air gap",
                    artifacts=evidence,
                )
            hits = io.iptables_reader(io.runner, internal_network_name(backend_id))
            return observe_egress(
                witness_log,
                iptables_available=hits is not None,
                iptables_hits=hits or 0,
                container_logs=container_logs,
            )
        finally:
            io.runner.run(
                airgap_compose_argv(base, overlay, backend_id, "down", "-v"), env=merged_env, timeout=_DOWN_TIMEOUT
            )

    return observe


def _environment_reasons(io: AirgapIO) -> list[str]:
    reasons: list[str] = []
    for argv, what in ((["docker", "--version"], "docker"), (["docker", "compose", "version"], "docker compose v2")):
        result = io.runner.run(argv, timeout=_PROBE_TIMEOUT)
        if not result.ok:
            detail = (result.stderr or result.stdout).strip().splitlines()
            reasons.append(f"{what} is not available: {detail[0] if detail else 'command failed'}")
    return reasons


def _persist_verdicts(verdicts_path: Path, verdicts: list[AirgapVerdict]) -> list[AirgapVerdict]:
    """Write verdicts.json, merging by backend so a ``--backend``-scoped re-run under the
    same run id refreshes that backend's verdict without discarding the other backend's
    persisted P4 evidence. Returns the full merged set for the report render."""
    verdicts_path.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, dict[str, object]] = {}
    if verdicts_path.is_file():
        try:
            existing = json.loads(verdicts_path.read_text(encoding="utf-8"))
            merged = {str(entry["backend"]): dict(entry) for entry in existing.get("verdicts", [])}
        except (OSError, ValueError, KeyError, TypeError):
            merged = {}  # corrupt prior file: rewrite from this run's verdicts alone
    merged.update({verdict.backend: verdict.to_dict() for verdict in verdicts})
    # Rebuild every merged entry BEFORE persisting: a prior-file entry that carries
    # `backend` but lacks the run payloads would otherwise KeyError here — after all
    # docker work succeeded — and cost this run its report. Unusable prior entries are
    # dropped exactly like a corrupt prior file; current-run entries always round-trip.
    rebuilt: list[AirgapVerdict] = []
    ordered: list[dict[str, object]] = []
    for backend in sorted(merged):
        entry = merged[backend]
        try:
            rebuilt.append(AirgapVerdict.from_dict(entry))
        except (KeyError, TypeError, ValueError):
            continue
        ordered.append(entry)
    payload = {"schema_version": 1, "verdicts": ordered}
    verdicts_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return rebuilt


def _verdict_phrase(verdict: AirgapVerdict) -> str:
    if verdict.air_gapped_confirmed:
        suffix = " (as-shipped egress recorded)" if verdict.leaks_as_shipped else ""
        return f"{verdict.backend}: air-gapped after opt-out{suffix}"
    return f"{verdict.backend}: egress persists after opt-out (evidence, not failure)"


def run_airgap(
    subtree_root: Path,
    settings: Settings,
    io: AirgapIO,
    *,
    env: Mapping[str, str],
    run_id: str,
    only_backend: str | None = None,
) -> PhaseResult:
    """P4: static gates -> prober build -> per-backend dual-scored observation."""
    artifacts_dir = settings.resolve_dir("artifacts_dir", subtree_root)
    reports_dir = settings.resolve_dir("reports_dir", subtree_root)
    backend_ids = [spec.id for spec in settings.backends]
    if only_backend is not None:
        backend_ids = [backend_id for backend_id in backend_ids if backend_id == only_backend]
        if not backend_ids:
            return PhaseResult("airgap", STATUS_FAIL, f"backend {only_backend!r} is not configured")

    probe_reasons = _environment_reasons(io)
    if probe_reasons:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "airgap (P4)",
            probe_reasons,
            "Install/start docker with compose v2 on this host, then re-run `make airgap`.",
            now_fn=io.now_fn,
        )
        return PhaseResult("airgap", STATUS_BLOCKED, probe_reasons[0], artifacts=(str(report),))

    violations: list[str] = []
    gated: list[_GatedBackend] = []
    for backend_id in backend_ids:
        backend_violations, gate = _gate_backend(settings.backend(backend_id), subtree_root)
        violations.extend(backend_violations)
        if gate is not None:
            gated.append(gate)
    violations.extend(dockerfile_pinned(subtree_root / "deploy" / "prober" / "Dockerfile"))
    if violations:
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "airgap (P4) — static gates",
            violations,
            "Commit compliant air-gap overlay(s) (internal network + witness + `ports: !reset []`), run "
            "`make pin-digests` where the registry is reachable, and re-run `make airgap`.",
            now_fn=io.now_fn,
        )
        return PhaseResult("airgap", STATUS_BLOCKED, violations[0], artifacts=(str(report),))

    build = io.runner.run(prober_build_argv(subtree_root, run_id), timeout=_BUILD_TIMEOUT)
    if not build.ok:
        reason = (
            f"prober image build failed (rc={build.returncode}, timed_out={build.timed_out}): "
            f"{(build.stderr or build.stdout).strip()[:400]}"
        )
        report = write_blocked_report(
            artifacts_dir,
            run_id,
            "airgap (P4) — prober build",
            [reason],
            "The prober image builds ONLINE (registry + pip access) — build during P1 on a connected "
            "host, fix the finding above, and re-run `make airgap`.",
            now_fn=io.now_fn,
        )
        return PhaseResult("airgap", STATUS_BLOCKED, reason, artifacts=(str(report),))

    verdicts: list[AirgapVerdict] = []
    for gate in gated:
        # Resource envelope + no ambiguity about who is answering: the NORMAL stack goes
        # down before its air-gapped twin comes up (distinct project, fresh volumes).
        if not down_stack(gate.spec, subtree_root, io.runner):
            logger.warning("airgap[%s]: normal-stack teardown failed; the air-gap `up` is the real gate", gate.spec.id)
        observe = _observe_factory(io, env, run_id, gate, artifacts_dir)
        try:
            verdicts.append(
                dual_score(gate.spec.id, gate.spec.airgap.as_shipped_env, gate.spec.airgap.opt_out_env, observe)
            )
        except ProberHaltError as exc:
            report = write_blocked_report(
                artifacts_dir,
                run_id,
                "airgap (P4) — prober HALT",
                [str(exc)],
                "A negative control PASSED inside the air-gapped re-run: either the matrix claim is wrong "
                "(a finding!) or the probe layer is broken. Review the prober/witness logs beside this "
                "report before ANY further runs.",
                now_fn=io.now_fn,
            )
            return PhaseResult("airgap", STATUS_HALT, str(exc), artifacts=(str(report), *exc.artifacts))
        except AirgapObservationError as exc:
            report = write_blocked_report(
                artifacts_dir,
                run_id,
                "airgap (P4) — observation",
                [str(exc)],
                "Inspect the prober/witness/container logs beside this report (a prober rc=3 usually means "
                "missing credentials in the environment), fix the finding, and re-run `make airgap`.",
                now_fn=io.now_fn,
            )
            return PhaseResult("airgap", STATUS_BLOCKED, str(exc), artifacts=(str(report), *exc.artifacts))

    verdicts_path = artifacts_dir / run_id / "airgap" / "verdicts.json"
    merged_verdicts = _persist_verdicts(verdicts_path, verdicts)
    report_path = write_report(reports_dir / "airgap_report.md", render_airgap_report(merged_verdicts))

    unconfirmed = [verdict.backend for verdict in verdicts if verdict.unconfirmed]
    if unconfirmed:
        reasons = [
            f"{backend}: opt-out observation unusable (dead witness, no iptables backstop) — cannot "
            "confirm OR deny the air gap"
            for backend in unconfirmed
        ]
        blocked = write_blocked_report(
            artifacts_dir,
            run_id,
            "airgap (P4) — unconfirmed verdicts",
            reasons,
            "An unusable observation routes to a human, never to a confirmed mark: check the witness "
            "sidecar attached and logged queries (the canary should always appear), then re-run.",
            now_fn=io.now_fn,
        )
        return PhaseResult(
            "airgap",
            STATUS_BLOCKED,
            reasons[0],
            artifacts=(str(blocked), str(verdicts_path), str(report_path)),
        )
    summary = "; ".join(_verdict_phrase(verdict) for verdict in verdicts)
    return PhaseResult(
        "airgap",
        STATUS_OK,
        f"dual-scored {len(verdicts)} backend(s): {summary}",
        artifacts=(str(verdicts_path), str(report_path)),
    )
