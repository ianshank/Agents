"""Unit tests for ops-burden metrics: stats parsing, medians, schema-validated write."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend_validation.deploy import ComposeImage, DeployOutcome
from backend_validation.metrics import (
    BackendMetrics,
    EffortMetricsFile,
    MetricsError,
    _mem_to_mb,
    _parse_stats_lines,
    container_count,
    image_disk_bytes,
    metrics_from_outcome,
    sample_idle_stats,
)
from backend_validation.procrun import CompletedCommand

SUBTREE = Path(__file__).resolve().parents[1]
SCHEMA = SUBTREE / "schemas" / "effort_metrics.schema.json"
_PINNED = ComposeImage(service="web", ref="postgres:16@sha256:" + "a" * 64)


class ScriptedRunner:
    def __init__(self, results: list[CompletedCommand]) -> None:
        self._results = list(results)
        self.last_stats_argv: list[str] | None = None

    def run(self, argv: list[str], **_kwargs: object) -> CompletedCommand:
        if "stats" in argv:
            self.last_stats_argv = list(argv)
        return self._results.pop(0) if self._results else CompletedCommand(tuple(argv), 0)


def _stats_line(cpu: str, mem: str) -> str:
    return json.dumps({"CPUPerc": cpu, "MemUsage": mem})


# ----------------------------------------------------------------- stats parsing
def test_mem_to_mb_units() -> None:
    assert _mem_to_mb("512MiB") == 512.0
    assert _mem_to_mb("1GiB") == 1024.0
    assert _mem_to_mb("2048KiB") == 2.0
    assert _mem_to_mb("garbage") == 0.0


def test_parse_stats_tolerates_noise() -> None:
    stdout = _stats_line("12.5%", "256MiB / 2GiB") + "\nnot json\n" + _stats_line("bad", "1MiB")
    parsed = _parse_stats_lines(stdout)
    assert parsed == [(12.5, 256.0)]  # the noise line and the bad-cpu line are skipped


def test_sample_idle_stats_medians_are_project_scoped() -> None:
    # First call is `docker ps` scoping to the project's containers (finding 2); then N sweeps.
    runner = ScriptedRunner(
        [
            CompletedCommand(("docker",), 0, stdout="id1\nid2\n"),  # project container ids
            CompletedCommand(("docker",), 0, stdout=_stats_line("10%", "100MiB")),
            CompletedCommand(("docker",), 0, stdout=_stats_line("20%", "200MiB")),
            CompletedCommand(("docker",), 0, stdout=_stats_line("30%", "300MiB")),
        ]
    )
    cpu, ram = sample_idle_stats("langfuse", runner, samples=3, interval_seconds=0, sleeper=lambda _s: None)
    assert cpu == 20.0 and ram == 200.0
    assert runner.last_stats_argv is not None
    assert runner.last_stats_argv[-2:] == ["id1", "id2"]  # stats was scoped to the project ids


def test_sample_idle_stats_null_when_ps_fails() -> None:
    runner = ScriptedRunner([CompletedCommand(("docker",), 1, stderr="daemon down")])
    assert sample_idle_stats("x", runner, samples=1, interval_seconds=0, sleeper=lambda _s: None) == (None, None)


def test_sample_idle_stats_null_when_no_project_containers() -> None:
    runner = ScriptedRunner([CompletedCommand(("docker",), 0, stdout="")])  # ps ok, zero ids
    assert sample_idle_stats("x", runner, samples=1, interval_seconds=0, sleeper=lambda _s: None) == (None, None)


def test_container_count_and_disk_bytes() -> None:
    assert container_count("opik", ScriptedRunner([CompletedCommand(("docker",), 0, stdout="a\nb\nc\n")])) == 3
    assert container_count("opik", ScriptedRunner([CompletedCommand(("docker",), 1)])) == 0
    disk = image_disk_bytes([_PINNED], ScriptedRunner([CompletedCommand(("docker",), 0, stdout="12345\n")]))
    assert disk == 12345
    assert image_disk_bytes([_PINNED], ScriptedRunner([CompletedCommand(("docker",), 1)])) is None


# ----------------------------------------------------------------- file writing
def test_effort_metrics_file_writes_valid_schema(tmp_path: Path) -> None:
    metrics = BackendMetrics(
        backend="langfuse",
        setup_wall_clock_seconds=42.1234,
        health_retries=3,
        container_count=6,
        images=[_PINNED],
        idle_cpu_percent_median=15.0,
        idle_ram_mb_median=900.0,
        disk_bytes=1_500_000_000,
        started_utc="2026-07-20T00:00:00+00:00",
    )
    metrics_file = EffortMetricsFile(path=tmp_path / "effort_metrics.json", schema_path=SCHEMA)
    metrics_file.record(metrics)
    written = metrics_file.write()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    entry = payload["backends"][0]
    assert entry["setup_wall_clock_seconds"] == 42.123  # rounded to 3 dp
    assert entry["all_images_pinned"] is True
    assert entry["images"][0]["digest"] == "sha256:" + "a" * 64
    assert "failure_count" not in entry  # removed: it was structurally pinned at 0


def test_effort_metrics_rejects_invalid_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = BackendMetrics(
        backend="x",
        setup_wall_clock_seconds=-1.0,
        health_retries=0,
        container_count=0,
        images=[],
    )
    metrics_file = EffortMetricsFile(path=tmp_path / "m.json", schema_path=SCHEMA)
    metrics_file.record(metrics)
    with pytest.raises(MetricsError, match="schema validation"):
        metrics_file.write()


def test_metrics_from_outcome_composes_all_sources() -> None:
    outcome = DeployOutcome(backend="opik", setup_wall_clock_seconds=30.0, health_retries=1, images=(_PINNED,))
    runner = ScriptedRunner(
        [
            CompletedCommand(("docker",), 0, stdout="s1\ns2\n"),  # ps for sample_idle_stats
            CompletedCommand(("docker",), 0, stdout=_stats_line("5%", "50MiB")),  # stats sample 1
            CompletedCommand(("docker",), 0, stdout="c1\nc2\n"),  # ps for container_count
            CompletedCommand(("docker",), 0, stdout="900\n"),  # image_disk_bytes
        ]
    )
    metrics = metrics_from_outcome(
        outcome,
        runner,
        started_utc="2026-07-20T00:00:00+00:00",
        stats_samples=1,
        stats_interval_seconds=0,
        sleeper=lambda _s: None,
    )
    assert metrics.container_count == 2 and metrics.disk_bytes == 900
    assert metrics.idle_cpu_percent_median == 5.0


def test_write_merges_existing_backends(tmp_path: Path) -> None:
    # Finding 5: a per-backend deploy must merge into (not clobber) prior runs.
    def _m(name: str) -> BackendMetrics:
        return BackendMetrics(
            backend=name, setup_wall_clock_seconds=1.0, health_retries=0, container_count=1, images=[_PINNED]
        )

    path = tmp_path / "effort_metrics.json"
    first = EffortMetricsFile(path=path, schema_path=SCHEMA)
    first.record(_m("langfuse"))
    first.write()
    # A fresh process (new EffortMetricsFile) records only opik and writes.
    second = EffortMetricsFile(path=path, schema_path=SCHEMA)
    second.record(_m("opik"))
    second.write()
    payload = json.loads(path.read_text(encoding="utf-8"))
    backends = {entry["backend"] for entry in payload["backends"]}
    assert backends == {"langfuse", "opik"}  # langfuse survived the second write


def test_write_refuses_corrupt_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "effort_metrics.json"
    path.write_text("{ not json", encoding="utf-8")
    metrics_file = EffortMetricsFile(path=path, schema_path=SCHEMA)
    metrics_file.record(
        BackendMetrics(backend="x", setup_wall_clock_seconds=1.0, health_retries=0, container_count=1, images=[_PINNED])
    )
    with pytest.raises(MetricsError, match="unreadable; refusing to overwrite"):
        metrics_file.write()
