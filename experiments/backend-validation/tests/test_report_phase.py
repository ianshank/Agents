"""Unit tests for the P5 report phase and the `all` chain (stop-on-BLOCKED/HALT)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend_validation.airgap import AirgapRun, AirgapVerdict, EgressObservation
from backend_validation.observables import Observable, ObservableLog, OpOutcome
from backend_validation.phases import STATUS_BLOCKED, STATUS_FAIL, STATUS_OK, PhaseResult
from backend_validation.report_phase import run_all, run_report
from backend_validation.settings import Settings, load_settings

_NOW = "2026-07-20T00:00:00+00:00"


def _settings(root: Path) -> Settings:
    return load_settings(root / "config.yaml", env={})


def _sign(root: Path) -> None:
    """Turn the tmp subtree into a signed one so report/marks can render.

    Also resolves every CLAIM_TBD to the absent mark — preflight blocks on unresolved
    claims, and the point of these tests is chaining, not the specific marks.
    """
    for name in ("PROBES.yaml", "RUBRIC.md"):
        text = (root / name).read_text(encoding="utf-8")
        text = text.replace("signed_off: false", "signed_off: true").replace("CLAIM_TBD", "—")
        (root / name).write_text(text, encoding="utf-8")
    lines = []
    for name in ("PROBES.yaml", "RUBRIC.md"):
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        lines.append(f"sha256 {digest}  {name}")
    lines.append("signed_by: test-reviewer")
    (root / "SIGNOFF").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_observables(root: Path, settings: Settings, run_id: str) -> None:
    artifacts = settings.resolve_dir("artifacts_dir", root)
    log = ObservableLog(artifacts / run_id / "observables.jsonl")
    seed: tuple[tuple[str, dict[str, object]], ...] = (
        ("create_trace", {}),
        ("fetch_trace", {"trace_visible": True}),
    )
    for backend in ("langfuse", "opik"):
        for operation, extra in seed:
            log.append(
                Observable(
                    probe_id="l1.tracing.roundtrip",
                    cell_id="tracing.observability",
                    backend=backend,
                    rep_index=0,
                    ts_utc=_NOW,
                    outcome=OpOutcome(operation=operation, status="ok", latency_ms=1.0),
                    extra=extra,
                )
            )


# -------------------------------------------------------------------- report
def test_report_blocks_when_unsigned(tmp_subtree: Path) -> None:
    result = run_report(tmp_subtree, _settings(tmp_subtree), run_id="r", now_fn=lambda: _NOW)
    assert result.status == STATUS_BLOCKED and "unsigned rubric" in result.reason


def test_report_blocks_without_observables(tmp_subtree: Path) -> None:
    _sign(tmp_subtree)
    result = run_report(tmp_subtree, _settings(tmp_subtree), run_id="empty", now_fn=lambda: _NOW)
    assert result.status == STATUS_BLOCKED and "no observables" in result.reason


def test_report_renders_when_signed_with_evidence(tmp_subtree: Path) -> None:
    _sign(tmp_subtree)
    settings = _settings(tmp_subtree)
    _seed_observables(tmp_subtree, settings, "run-x")
    result = run_report(tmp_subtree, settings, run_id="run-x", now_fn=lambda: _NOW)
    assert result.status == STATUS_OK, result.reason
    body = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert "claimed (matrix)" in body and "observed (mechanical)" in body
    assert "recommendation" not in body.lower()
    assert len(result.artifacts) == 1  # no verdicts.json for this run -> no airgap render


def _seed_verdicts(root: Path, settings: Settings, run_id: str) -> Path:
    def _run(label: str, *, usable: bool, domains: tuple[str, ...] = ()) -> AirgapRun:
        return AirgapRun(
            backend="langfuse",
            config_label=label,
            env={},
            observation=EgressObservation(
                mechanism="dns-witness",
                attempted_domains=domains,
                degraded=True,
                egress_detected=bool(domains),
                usable=usable,
            ),
        )

    verdict = AirgapVerdict(
        backend="langfuse",
        as_shipped=_run("as-shipped", usable=True, domains=("stats.comet.com",)),
        opt_out=_run("opt-out", usable=True),
    )
    path = settings.resolve_dir("artifacts_dir", root) / run_id / "airgap" / "verdicts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "verdicts": [verdict.to_dict()]}), encoding="utf-8")
    return path


def test_report_rerenders_airgap_report_from_persisted_verdicts(tmp_subtree: Path) -> None:
    _sign(tmp_subtree)
    settings = _settings(tmp_subtree)
    _seed_observables(tmp_subtree, settings, "run-a")
    _seed_verdicts(tmp_subtree, settings, "run-a")
    result = run_report(tmp_subtree, settings, run_id="run-a", now_fn=lambda: _NOW)
    assert result.status == STATUS_OK, result.reason
    airgap_paths = [artifact for artifact in result.artifacts if artifact.endswith("airgap_report.md")]
    assert len(airgap_paths) == 1
    body = Path(airgap_paths[0]).read_text(encoding="utf-8")
    assert "stats.comet.com" in body and "| langfuse |" in body and "yes" in body


def test_report_fails_loud_on_corrupt_verdicts(tmp_subtree: Path) -> None:
    _sign(tmp_subtree)
    settings = _settings(tmp_subtree)
    _seed_observables(tmp_subtree, settings, "run-b")
    path = _seed_verdicts(tmp_subtree, settings, "run-b")
    path.write_text("{not json", encoding="utf-8")
    result = run_report(tmp_subtree, settings, run_id="run-b", now_fn=lambda: _NOW)
    assert result.status == STATUS_FAIL and "airgap verdicts unreadable" in result.reason
    path.write_text(json.dumps({"schema_version": 1, "verdicts": [{"backend": "x"}]}), encoding="utf-8")
    result = run_report(tmp_subtree, settings, run_id="run-b", now_fn=lambda: _NOW)
    assert result.status == STATUS_FAIL  # KeyError path (missing as_shipped) fails loud too


# --------------------------------------------------------------------- all
def test_all_stops_at_unsigned_preflight(tmp_subtree: Path) -> None:
    def _fake_l2(*_args: object, **_kwargs: object) -> PhaseResult:
        raise AssertionError("l2 should not run when preflight blocks")

    results = run_all(tmp_subtree, _settings(tmp_subtree), run_id="r", now_fn=lambda: _NOW, l2_runner=_fake_l2)
    # Preflight blocks (unsigned) -> the chain stops immediately.
    assert len(results) == 1 and results[0].phase == "preflight"
    assert results[0].status == STATUS_BLOCKED


def test_all_chains_through_report_when_signed(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    settings = _settings(tmp_subtree)

    # Fake the environment as ready so preflight passes; keep L1 with failing controls so it
    # records evidence without HALTing (default-fail Null client via the real build_client).
    import backend_validation.phases as phases

    def _ready_io(*_a: object, **_k: object) -> phases.PhaseIO:
        from backend_validation.clients import NullProbeClient

        def _factory(spec: object, judge: object = None, **_kw: object) -> NullProbeClient:
            return NullProbeClient(
                backend_id=getattr(spec, "id", "x"),
                script={
                    op: OpOutcome(operation=op, status="error", latency_ms=1.0)
                    for op in ("probe_endpoint", "invoke_redteam", "invoke_guardrail")
                },
            )

        return phases.PhaseIO(
            runner_run=lambda _argv: (True, "ok"),
            disk_free_gb=lambda _p: 999.0,
            port_is_free=lambda _p: True,
            client_factory=_factory,
            now_fn=lambda: _NOW,
        )

    monkeypatch.setattr(phases, "default_phase_io", _ready_io)
    monkeypatch.setattr("backend_validation.report_phase.default_phase_io", _ready_io)

    def _l2(*_args: object, **_kwargs: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_BLOCKED, "harness not installed in this unit env")

    results = run_all(tmp_subtree, settings, run_id="run-all", now_fn=lambda: _NOW, l2_runner=_l2)
    phases_seen = [result.phase for result in results]
    assert phases_seen == ["preflight", "l1", "l2", "report"]  # chained to the end
    assert results[0].status == STATUS_OK and results[-1].status == STATUS_OK


def test_report_fails_on_unreadable_tcb(tmp_subtree: Path) -> None:
    (tmp_subtree / "PROBES.yaml").write_text("not: [valid", encoding="utf-8")
    result = run_report(tmp_subtree, _settings(tmp_subtree), run_id="r", now_fn=lambda: _NOW)
    assert result.status == "FAIL" and "TCB artifacts unreadable" in result.reason


def test_all_stops_when_l1_halts(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    import backend_validation.phases as phases

    # Ready environment, but the L1 client makes the unreachable control "pass" -> HALT.
    def _halting_io(*_a: object, **_k: object) -> phases.PhaseIO:
        from backend_validation.clients import NullProbeClient

        return phases.PhaseIO(
            runner_run=lambda _argv: (True, "ok"),
            disk_free_gb=lambda _p: 999.0,
            port_is_free=lambda _p: True,
            client_factory=lambda spec, judge=None, **_kw: NullProbeClient(backend_id=getattr(spec, "id", "x")),
            now_fn=lambda: _NOW,
        )

    monkeypatch.setattr("backend_validation.report_phase.default_phase_io", _halting_io)

    def _l2(*_a: object, **_k: object) -> PhaseResult:
        raise AssertionError("l2 must not run after an L1 HALT")

    results = run_all(tmp_subtree, _settings(tmp_subtree), run_id="halt", now_fn=lambda: _NOW, l2_runner=_l2)
    assert [r.phase for r in results] == ["preflight", "l1"]
    assert results[-1].status == "HALT"


# ------------------------------------------------------------- airgap seam (P4)
def _patch_ready_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ready environment + evidence-recording (non-HALTing) L1, as in the chain test."""
    import backend_validation.phases as phases

    def _ready_io(*_a: object, **_k: object) -> phases.PhaseIO:
        from backend_validation.clients import NullProbeClient

        def _factory(spec: object, judge: object = None, **_kw: object) -> NullProbeClient:
            return NullProbeClient(
                backend_id=getattr(spec, "id", "x"),
                script={
                    op: OpOutcome(operation=op, status="error", latency_ms=1.0)
                    for op in ("probe_endpoint", "invoke_redteam", "invoke_guardrail")
                },
            )

        return phases.PhaseIO(
            runner_run=lambda _argv: (True, "ok"),
            disk_free_gb=lambda _p: 999.0,
            port_is_free=lambda _p: True,
            client_factory=_factory,
            now_fn=lambda: _NOW,
        )

    monkeypatch.setattr("backend_validation.report_phase.default_phase_io", _ready_io)


def test_all_with_blocked_airgap_still_renders_report(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    _patch_ready_io(monkeypatch)
    seen: dict[str, object] = {}

    def _l2(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_BLOCKED, "harness not installed")

    def _airgap(subtree_root: Path, settings: Settings, *, run_id: str, now_fn: object) -> PhaseResult:
        seen["run_id"] = run_id
        return PhaseResult("airgap", STATUS_BLOCKED, "docker is not available")

    results = run_all(
        tmp_subtree, _settings(tmp_subtree), run_id="ag-b", now_fn=lambda: _NOW, l2_runner=_l2, airgap_runner=_airgap
    )
    # BLOCKED airgap mirrors BLOCKED L2: recorded, non-zero exit surfaced, report still rendered.
    assert [r.phase for r in results] == ["preflight", "l1", "l2", "airgap", "report"]
    assert results[3].status == STATUS_BLOCKED and results[-1].status == STATUS_OK
    assert seen["run_id"] == "ag-b"  # the chain's run id threads into the airgap runner


def test_all_stops_when_airgap_hard_fails(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    _patch_ready_io(monkeypatch)

    def _l2(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_BLOCKED, "harness not installed")

    def _airgap(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("airgap", STATUS_FAIL, "backend 'mlflow' is not configured")

    results = run_all(
        tmp_subtree, _settings(tmp_subtree), run_id="ag-f", now_fn=lambda: _NOW, l2_runner=_l2, airgap_runner=_airgap
    )
    assert [r.phase for r in results] == ["preflight", "l1", "l2", "airgap"]  # report never reached
    assert results[-1].status == STATUS_FAIL


def test_all_stops_when_airgap_halts(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    _patch_ready_io(monkeypatch)

    def _l2(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_BLOCKED, "harness not installed")

    def _airgap(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("airgap", "HALT", "prober HALTed (rc=4)")

    results = run_all(
        tmp_subtree, _settings(tmp_subtree), run_id="ag-h", now_fn=lambda: _NOW, l2_runner=_l2, airgap_runner=_airgap
    )
    assert [r.phase for r in results] == ["preflight", "l1", "l2", "airgap"]
    assert results[-1].status == "HALT"


def test_all_without_airgap_runner_is_unchanged(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Default airgap_runner=None: the chain is byte-identical to the pre-P4 behavior.
    _sign(tmp_subtree)
    _patch_ready_io(monkeypatch)

    def _l2(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_BLOCKED, "harness not installed")

    results = run_all(tmp_subtree, _settings(tmp_subtree), run_id="ag-n", now_fn=lambda: _NOW, l2_runner=_l2)
    assert [r.phase for r in results] == ["preflight", "l1", "l2", "report"]  # no airgap phase appears


def test_all_stops_when_l2_hard_fails(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _sign(tmp_subtree)
    settings = _settings(tmp_subtree)
    import backend_validation.phases as phases

    def _ready_io(*_a: object, **_k: object) -> phases.PhaseIO:
        from backend_validation.clients import NullProbeClient

        def _factory(spec: object, judge: object = None, **_kw: object) -> NullProbeClient:
            return NullProbeClient(
                backend_id=getattr(spec, "id", "x"),
                script={
                    op: OpOutcome(operation=op, status="error", latency_ms=1.0)
                    for op in ("probe_endpoint", "invoke_redteam", "invoke_guardrail")
                },
            )

        return phases.PhaseIO(
            runner_run=lambda _argv: (True, "ok"),
            disk_free_gb=lambda _p: 999.0,
            port_is_free=lambda _p: True,
            client_factory=_factory,
            now_fn=lambda: _NOW,
        )

    monkeypatch.setattr("backend_validation.report_phase.default_phase_io", _ready_io)

    def _l2_fail(*_a: object, **_k: object) -> PhaseResult:
        return PhaseResult("l2", STATUS_FAIL, "Opik sink is not conformant")

    results = run_all(tmp_subtree, settings, run_id="l2fail", now_fn=lambda: _NOW, l2_runner=_l2_fail)
    assert [r.phase for r in results] == ["preflight", "l1", "l2"]  # report never reached
    assert results[-1].status == STATUS_FAIL
