"""Compose deployment orchestration with digest refusal and health verification (P1).

Reproducibility rules (spec R11): every image in a compose file must be pinned by digest —
``deploy`` REFUSES to start anything unpinned (a ``TODO_PIN`` marker committed where the
registry was unreachable is exactly what this refusal is for). Setup wall-clock, health
retries, and failure counts are first-class ops-burden EVIDENCE (spec R9), captured here
and written by ``metrics``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from backend_validation.logging_util import get_logger
from backend_validation.procrun import CommandRunner
from backend_validation.settings import BackendSpec, Settings

logger = get_logger(__name__)

_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
_IMAGE_LINE = re.compile(r"^(?P<indent>\s+image:\s*)(?P<ref>\S+)\s*$")
# A Docker named volume: a bare token with no path separators and no leading dot/slash.
# Anything else in a `volumes:` source position is a host bind mount and must stay in-subtree.
_NAMED_VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class DeployError(RuntimeError):
    """Deployment precondition failure; phases convert it to BLOCKED."""


@dataclass(frozen=True)
class ComposeImage:
    service: str
    ref: str

    @property
    def pinned(self) -> bool:
        return bool(_DIGEST_RE.search(self.ref))

    @property
    def digest(self) -> str | None:
        match = _DIGEST_RE.search(self.ref)
        return match.group(0).removeprefix("@") if match else None


def compose_images(compose_path: Path) -> list[ComposeImage]:
    try:
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeployError(f"cannot read compose file {compose_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise DeployError(f"compose file {compose_path} is not valid YAML: {exc}") from exc
    services = (data or {}).get("services")
    if not isinstance(services, dict) or not services:
        raise DeployError(f"compose file {compose_path} declares no services")
    images: list[ComposeImage] = []
    for name, service in sorted(services.items()):
        image_ref = service.get("image") if isinstance(service, dict) else None
        if not image_ref:
            raise DeployError(f"service {name!r} in {compose_path} has no image (build: is not allowed here)")
        images.append(ComposeImage(service=str(name), ref=str(image_ref)))
    return images


def refuse_unpinned(compose_path: Path) -> list[ComposeImage]:
    """The digest gate: every image must carry @sha256:<64hex>; anything else refuses."""
    images = compose_images(compose_path)
    unpinned = [image for image in images if not image.pinned]
    if unpinned:
        offenders = ", ".join(f"{image.service}={image.ref}" for image in unpinned)
        raise DeployError(
            f"unpinned image(s) in {compose_path.name}: {offenders} — run `make pin-digests` "
            "where the registry is reachable and commit the result (never deploy unpinned)"
        )
    return images


def bind_mounts_inside(compose_path: Path, subtree_root: Path) -> list[str]:
    """Zero-writes invariant for containers: host bind mounts must resolve inside the
    subtree. Named volumes are fine (docker-managed). Returns violations."""
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    violations: list[str] = []
    root = subtree_root.resolve()
    for name, service in sorted((data.get("services") or {}).items()):
        for volume in (service or {}).get("volumes", []) or []:
            source = volume.split(":", 1)[0] if isinstance(volume, str) else str((volume or {}).get("source", ""))
            if _NAMED_VOLUME.fullmatch(source):
                continue  # docker-managed named volume (no path separators, no leading dot/slash)
            # Everything else is a bind mount whose containment must be checked. Classifying by
            # what is NOT a named volume (rather than by a "./"/"/" prefix) closes the gap where
            # `../escape` and bare `.` slipped through as if they were named volumes.
            # Joining an absolute source onto compose_path.parent discards the parent, so one
            # resolve() handles both absolute and relative sources.
            resolved = (compose_path.parent / source).resolve()
            if not resolved.is_relative_to(root):
                violations.append(f"{compose_path.name}:{name}: bind mount {source} escapes the subtree")
    return violations


@dataclass(frozen=True)
class DeployOutcome:
    backend: str
    setup_wall_clock_seconds: float
    health_retries: int
    failure_count: int
    images: tuple[ComposeImage, ...]


def project_name(backend_id: str) -> str:
    return f"bv-{backend_id}"


def compose_argv(compose_path: Path, backend_id: str, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(compose_path), "-p", project_name(backend_id), *args]


def deploy_stack(
    spec: BackendSpec,
    settings: Settings,
    subtree_root: Path,
    runner: CommandRunner,
    *,
    env: Mapping[str, str],
    health_check: Callable[[str], bool],
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
    health_attempts: int = 30,
    health_interval_seconds: float = 5.0,
) -> DeployOutcome:
    """Digest-check, ``compose up -d --wait``, then app-level health poll with counting."""
    compose_path = subtree_root / spec.compose_file
    images = refuse_unpinned(compose_path)
    mount_violations = bind_mounts_inside(compose_path, subtree_root)
    if mount_violations:
        raise DeployError("; ".join(mount_violations))
    started = clock()
    failures = 0
    up = runner.run(compose_argv(compose_path, spec.id, "up", "-d", "--wait"), env=dict(env), timeout=1800)
    if not up.ok:
        raise DeployError(
            f"compose up for {spec.id} failed (rc={up.returncode}, timed_out={up.timed_out}): "
            f"{(up.stderr or up.stdout).strip()[:400]}"
        )
    retries = 0
    healthy = health_check(spec.base_url)
    while not healthy and retries < health_attempts:
        sleeper(health_interval_seconds)
        retries += 1
        healthy = health_check(spec.base_url)
    if not healthy:
        failures += 1
        raise DeployError(
            f"{spec.id} containers came up but the app at {spec.base_url} never answered "
            f"({retries} poll(s)); see `docker compose -p {project_name(spec.id)} logs`"
        )
    elapsed = clock() - started
    logger.info("deploy[%s]: healthy in %.1fs after %d poll retries", spec.id, elapsed, retries)
    return DeployOutcome(
        backend=spec.id,
        setup_wall_clock_seconds=elapsed,
        health_retries=retries,
        failure_count=failures,
        images=tuple(images),
    )


def down_stack(spec: BackendSpec, subtree_root: Path, runner: CommandRunner) -> bool:
    compose_path = subtree_root / spec.compose_file
    result = runner.run(compose_argv(compose_path, spec.id, "down", "-v"), timeout=600)
    return result.ok


# ------------------------------------------------------------------ digest pinning
def resolve_digest(image_ref: str, runner: CommandRunner) -> str:
    """Resolve a tag to its manifest(-list) digest via `docker manifest inspect -v`."""
    result = runner.run(["docker", "manifest", "inspect", "--verbose", image_ref], timeout=120)
    if not result.ok:
        raise DeployError(f"docker manifest inspect failed for {image_ref}: {result.stderr.strip()[:200]}")
    match = re.search(r'"digest":\s*"(sha256:[0-9a-f]{64})"', result.stdout)
    if not match:
        raise DeployError(f"no digest found in manifest output for {image_ref}")
    return match.group(1)


def pin_compose_file(compose_path: Path, runner: CommandRunner) -> list[tuple[str, str]]:
    """Rewrite unpinned/TODO image lines in place to tag@sha256:...; returns (ref, digest).

    Line-based on purpose: a YAML round-trip would destroy comments and formatting in a
    reviewed file. Only `image:` lines change, nothing else.
    """
    lines = compose_path.read_text(encoding="utf-8").splitlines(keepends=True)
    pinned: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        match = _IMAGE_LINE.match(line.rstrip("\n"))
        if not match:
            continue
        ref = match.group("ref")
        base = ref.split("@", 1)[0]
        if _DIGEST_RE.search(ref):
            continue  # already pinned
        digest = resolve_digest(base, runner)
        lines[index] = f"{match.group('indent')}{base}@{digest}\n"
        pinned.append((base, digest))
    if pinned:
        compose_path.write_text("".join(lines), encoding="utf-8")
    return pinned
