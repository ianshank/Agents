"""Unit tests for phase orchestration: preflight gates and L1 with faked environments."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from backend_validation.clients import MissingCredentialsError, NullProbeClient, ProbeClient
from backend_validation.observables import ObservableLog, OpOutcome
from backend_validation.phases import (
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_HALT,
    STATUS_OK,
    PhaseIO,
    run_l1,
    run_preflight,
    write_blocked_report,
)
from backend_validation.settings import BackendSpec, JudgeSpec, Settings, load_settings

_NOW = "2026-07-20T00:00:00+00:00"


def _settings(root: Path) -> Settings:
    return load_settings(root / "config.yaml", env={})


def _expected_fail_script() -> dict[str, OpOutcome]:
    """Ops that MUST fail for the negative controls to be confirmed absent."""
    return {
        operation: OpOutcome(operation=operation, status="error", latency_ms=1.0, stderr="refused")
        for operation in ("probe_endpoint", "invoke_redteam", "invoke_guardrail")
    }


def _io(
    *,
    client: ProbeClient | None = None,
    docker_ok: bool = True,
    free_gb: float = 999.0,
    ports_free: bool = True,
    raise_missing_credentials: bool = False,
) -> PhaseIO:
    def _factory(spec: BackendSpec, judge: JudgeSpec | None = None, **_kw: object) -> ProbeClient:
        if raise_missing_credentials:
            raise MissingCredentialsError(f"set env vars for {spec.id}")
        if client is not None:
            return client
        return NullProbeClient(backend_id=spec.id, script=_expected_fail_script())

    return PhaseIO(
        runner_run=lambda argv: (docker_ok, "ok" if docker_ok else "docker: not found"),
        disk_free_gb=lambda _path: free_gb,
        port_is_free=lambda _port: ports_free,
        client_factory=_factory,
        now_fn=lambda: _NOW,
    )


# -------------------------------------------------------------------- preflight
def test_preflight_schema_only_passes_on_the_committed_artifacts(tmp_subtree: Path) -> None:
    result = run_preflight(tmp_subtree, _settings(tmp_subtree), _io(), schema_only=True)
    assert result.status == STATUS_OK
    assert "sign-off not checked" in result.reason


def test_preflight_full_blocks_while_unsigned_and_writes_report(tmp_subtree: Path) -> None:
    result = run_preflight(tmp_subtree, _settings(tmp_subtree), _io())
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    report = Path(result.artifacts[0])
    assert report.is_file() and report.name == "blocked_report.md"
    body = report.read_text(encoding="utf-8")
    assert "signed_off is false" in body
    assert "CLAIM_TBD" in body
    assert "Agents never perform the sign-off" in body
    assert str(tmp_subtree) in str(report)  # evidence stays inside the (tmp) subtree


def test_preflight_reports_environment_failures(tmp_subtree: Path) -> None:
    result = run_preflight(tmp_subtree, _settings(tmp_subtree), _io(docker_ok=False, free_gb=1.0, ports_free=False))
    assert result.status == STATUS_BLOCKED
    body = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert "docker is not available" in body
    assert "below the configured minimum" in body
    assert "already bound" in body


def test_preflight_fails_on_structural_damage(tmp_subtree: Path) -> None:
    (tmp_subtree / "PROBES.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    result = run_preflight(tmp_subtree, _settings(tmp_subtree), _io(), schema_only=True)
    assert result.status == STATUS_FAIL and result.exit_code == 1
    assert "structural validation" in result.reason


# --------------------------------------------------------------------------- l1
def test_l1_happy_path_records_observables(tmp_subtree: Path) -> None:
    settings = _settings(tmp_subtree)
    result = run_l1(tmp_subtree, settings, _io(), run_id="run-test")
    assert result.status == STATUS_OK, result.reason
    log = ObservableLog(Path(result.artifacts[0]))
    observables = log.read_all()
    assert observables, "expected persisted evidence"
    backends = {observable.backend for observable in observables}
    assert backends == {"langfuse", "opik"}
    cells = {observable.cell_id for observable in observables}
    assert "tracing.observability" in cells
    assert "playground" not in {cell for cell in cells}  # human-only cells never probed
    # judge_k3 cells ran three repetitions
    rag_reps = {obs.rep_index for obs in observables if obs.cell_id == "rag.metrics"}
    assert rag_reps == {0, 1, 2}


def test_l1_halts_when_a_synthetic_control_passes(tmp_subtree: Path) -> None:
    # A default-ok client makes the unreachable-endpoint control "succeed" -> HALT.
    result = run_l1(tmp_subtree, _settings(tmp_subtree), _io(client=NullProbeClient(backend_id="x")), run_id="run-halt")
    assert result.status == STATUS_HALT and result.exit_code == 4
    assert "unexpected control PASS" in result.reason
    report = Path(result.artifacts[0])
    assert "negative controls" in report.read_text(encoding="utf-8")


def test_l1_blocks_on_missing_credentials(tmp_subtree: Path) -> None:
    result = run_l1(tmp_subtree, _settings(tmp_subtree), _io(raise_missing_credentials=True), run_id="run-creds")
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "set env vars" in result.reason


def test_l1_unknown_backend_filter_fails(tmp_subtree: Path) -> None:
    result = run_l1(tmp_subtree, _settings(tmp_subtree), _io(), run_id="run-x", only_backend="mlflow")
    assert result.status == STATUS_FAIL


def test_l1_single_backend_filter(tmp_subtree: Path) -> None:
    result = run_l1(tmp_subtree, _settings(tmp_subtree), _io(), run_id="run-one", only_backend="opik")
    assert result.status == STATUS_OK
    observables = ObservableLog(Path(result.artifacts[0])).read_all()
    assert {observable.backend for observable in observables} == {"opik"}


# ------------------------------------------------------------------ blocked writer
def test_write_blocked_report_shape(tmp_path: Path) -> None:
    path = write_blocked_report(
        tmp_path, "run-9", "deploy (P1)", ["stack unhealthy"], "Fix compose.", now_fn=lambda: _NOW
    )
    body = path.read_text(encoding="utf-8")
    assert body.startswith("# BLOCKED — deploy (P1)")
    assert "- stack unhealthy" in body and "Fix compose." in body and _NOW in body


def test_l1_engine_error_becomes_blocked_not_crash(tmp_subtree: Path) -> None:
    # Finding 6: an unexpected probe/client exception must fail-safe to a BLOCKED report
    # (exit 3) with the traceback logged, never crash the CLI with exit 1.
    class _Boom(NullProbeClient):
        def execute(self, operation: str, payload: Mapping[str, object]) -> OpOutcome:
            raise KeyError("malformed SDK response")

    io = _io(client=_Boom(backend_id="langfuse"))
    result = run_l1(tmp_subtree, _settings(tmp_subtree), io, run_id="run-boom")
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "engine error" in result.reason and "KeyError" in result.reason
    assert "engine error" in Path(result.artifacts[0]).read_text(encoding="utf-8")
