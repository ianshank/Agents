"""Ops-burden metrics (spec R9): numbers are evidence for the report, never judgments.

Captures per-backend deploy effort (wall-clock, retries, container count, idle RAM/CPU
medians after a settle period, image sizes) into ``effort_metrics.json``, validated
against ``schemas/effort_metrics.schema.json`` on every write — a malformed metrics file
would silently corrupt the P5 report otherwise.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from backend_validation.deploy import ComposeImage, DeployOutcome, project_name
from backend_validation.logging_util import get_logger
from backend_validation.procrun import CommandRunner

logger = get_logger(__name__)


class MetricsError(RuntimeError):
    """Raised when produced metrics do not validate against the schema."""


@dataclass
class BackendMetrics:
    backend: str
    setup_wall_clock_seconds: float
    health_retries: int
    container_count: int
    images: list[ComposeImage]
    idle_cpu_percent_median: float | None = None
    idle_ram_mb_median: float | None = None
    disk_bytes: int | None = None
    started_utc: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "setup_wall_clock_seconds": round(self.setup_wall_clock_seconds, 3),
            "health_retries": self.health_retries,
            "container_count": self.container_count,
            "idle_cpu_percent_median": self.idle_cpu_percent_median,
            "idle_ram_mb_median": self.idle_ram_mb_median,
            "disk_bytes": self.disk_bytes,
            "images": [{"name": image.ref, "digest": image.digest, "pinned": image.pinned} for image in self.images],
            "all_images_pinned": all(image.pinned for image in self.images),
            "started_utc": self.started_utc,
            "notes": self.notes,
        }


def _parse_stats_lines(stdout: str) -> list[tuple[float, float]]:
    """Parse `docker stats --no-stream --format json` lines -> (cpu%, mem MB)."""
    samples: list[tuple[float, float]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # docker interleaves warnings on stderr sometimes; stay tolerant here
        cpu_raw = str(record.get("CPUPerc", "")).rstrip("%")
        mem_raw = str(record.get("MemUsage", "")).split("/")[0].strip()
        try:
            cpu = float(cpu_raw)
        except ValueError:
            continue
        samples.append((cpu, _mem_to_mb(mem_raw)))
    return samples


def _mem_to_mb(text: str) -> float:
    units = {"KIB": 1 / 1024, "MIB": 1.0, "GIB": 1024.0, "B": 1 / (1024 * 1024)}
    upper = text.upper()
    for suffix, factor in units.items():
        if upper.endswith(suffix):
            try:
                return float(upper.removesuffix(suffix)) * factor
            except ValueError:
                return 0.0
    return 0.0


def _project_container_ids(backend_id: str, runner: CommandRunner) -> list[str] | None:
    """Container ids of THIS backend's compose project (None if docker ps failed)."""
    result = runner.run(
        ["docker", "ps", "--filter", f"label=com.docker.compose.project={project_name(backend_id)}", "-q"],
        timeout=60,
    )
    if not result.ok:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def sample_idle_stats(
    backend_id: str,
    runner: CommandRunner,
    *,
    samples: int,
    interval_seconds: float,
    sleeper: Callable[[float], None],
) -> tuple[float | None, float | None]:
    """Median idle CPU%/RAM across N sweeps of THIS backend's project containers only.

    Scoping ``docker stats`` to the project's container ids is load-bearing: run_deploy
    measures each backend without tearing down the previous one, so an unfiltered
    host-wide sweep would fold co-resident stacks (other backends, the judge) into this
    backend's ops-burden numbers.
    """
    ids = _project_container_ids(backend_id, runner)
    if not ids:  # None (ps failed) or [] (nothing running for this project)
        return None, None
    cpu_totals: list[float] = []
    mem_totals: list[float] = []
    for index in range(samples):
        if index:
            sleeper(interval_seconds)
        result = runner.run(["docker", "stats", "--no-stream", "--format", "json", *ids], timeout=60)
        if not result.ok:
            logger.warning("docker stats failed (%s); idle metrics recorded as null", result.stderr.strip()[:120])
            return None, None
        parsed = _parse_stats_lines(result.stdout)
        if parsed:
            cpu_totals.append(sum(cpu for cpu, _mem in parsed))
            mem_totals.append(sum(mem for _cpu, mem in parsed))
    if not cpu_totals:
        return None, None
    return round(statistics.median(cpu_totals), 2), round(statistics.median(mem_totals), 1)


def container_count(backend_id: str, runner: CommandRunner) -> int:
    ids = _project_container_ids(backend_id, runner)
    return len(ids) if ids is not None else 0


def image_disk_bytes(images: list[ComposeImage], runner: CommandRunner) -> int | None:
    total = 0
    for image in images:
        result = runner.run(["docker", "image", "inspect", "--format", "{{.Size}}", image.ref], timeout=60)
        if not result.ok:
            return None  # honest null beats a partial sum presented as a total
        try:
            total += int(result.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return None
    return total


@dataclass
class EffortMetricsFile:
    """Read-merge-write wrapper for effort_metrics.json with schema validation."""

    path: Path
    schema_path: Path
    backends: dict[str, BackendMetrics] = field(default_factory=dict)

    def record(self, metrics: BackendMetrics) -> None:
        self.backends[metrics.backend] = metrics

    def _load_existing(self) -> dict[str, dict[str, object]]:
        """Existing per-backend entries keyed by backend, so a single-backend deploy merges
        into (never clobbers) prior runs. A corrupt existing file fails loud rather than
        silently discarding recorded ops-burden evidence."""
        if not self.path.exists():
            return {}
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
            entries = existing["backends"]
            return {str(entry["backend"]): dict(entry) for entry in entries}
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
            raise MetricsError(
                f"existing effort metrics at {self.path} are unreadable; refusing to overwrite: {exc}"
            ) from exc

    def write(self) -> Path:
        merged = self._load_existing()
        for name, metrics in self.backends.items():
            merged[name] = metrics.to_dict()  # this run's backends win for their own keys
        payload = {"schema_version": 1, "backends": [merged[key] for key in sorted(merged)]}
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError as exc:
            raise MetricsError(f"effort metrics failed schema validation: {exc.message}") from exc
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return self.path


def metrics_from_outcome(
    outcome: DeployOutcome,
    runner: CommandRunner,
    *,
    started_utc: str,
    stats_samples: int,
    stats_interval_seconds: float,
    sleeper: Callable[[float], None],
) -> BackendMetrics:
    cpu_median, ram_median = sample_idle_stats(
        outcome.backend, runner, samples=stats_samples, interval_seconds=stats_interval_seconds, sleeper=sleeper
    )
    return BackendMetrics(
        backend=outcome.backend,
        setup_wall_clock_seconds=outcome.setup_wall_clock_seconds,
        health_retries=outcome.health_retries,
        container_count=container_count(outcome.backend, runner),
        images=list(outcome.images),
        idle_cpu_percent_median=cpu_median,
        idle_ram_mb_median=ram_median,
        disk_bytes=image_disk_bytes(list(outcome.images), runner),
        started_utc=started_utc,
    )
