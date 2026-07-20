"""L2 integration tests: sink conformance, adapter delta, gate ingestion, precondition.

These require the harness (``eval_harness``); ``make install`` installs it editable so the
gate covers them. Guarded with importorskip so an offline dev without the harness still
gets a green (skipped) run rather than a hard error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("eval_harness", reason="L2 probes require the eval harness sink seam")

from backend_validation.l2_phase import (
    _canonical_run,
    _gate_ingestion_ok,
    _langfuse_scorecalls,
    _opik_scorecalls,
    run_l2,
)
from backend_validation.phases import STATUS_BLOCKED, STATUS_OK
from backend_validation.probes import l2_sink
from backend_validation.settings import Settings, load_settings

SUBTREE = Path(__file__).resolve().parents[1]
_NOW = "2026-07-20T00:00:00+00:00"

pytestmark = [pytest.mark.l2]


def _settings(root: Path) -> Settings:
    return load_settings(root / "config.yaml", env={})


# ------------------------------------------------------------------ precondition
def test_precondition_passes_when_harness_present() -> None:
    result = l2_sink.check_precondition()
    assert result.ok and result.missing == ()


def test_precondition_reports_missing_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    real = importlib.util.find_spec

    def _fake(name: str, package: str | None = None) -> object:
        if name == "eval_harness.gating":
            return None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", _fake)
    result = l2_sink.check_precondition()
    assert not result.ok
    assert any("eval_harness.gating" in item for item in result.missing)


# ------------------------------------------------------------- the OpikSink adapter
def test_opik_sink_mirrors_langfuse_score_calls() -> None:
    run = _canonical_run(lambda: _NOW)
    assert _langfuse_scorecalls(run) == _opik_scorecalls(run)  # conformance: identical score set


def test_opik_sink_honours_threshold() -> None:
    run = _canonical_run(lambda: _NOW)
    client = l2_sink.NullOpikScoreClient()
    l2_sink.build_opik_sink(client, min_value_to_log=0.5).emit(run)
    # item 'b' faithfulness 0.4 is below the threshold and must be dropped.
    values = sorted(score["value"] for score in client.scores)
    assert 0.4 not in values and client.flushed == 1


def test_null_opik_client_records_and_flushes() -> None:
    client = l2_sink.NullOpikScoreClient()
    client.log_score(run_id="r", item_id="i", name="n", value=1.0, comment=None)
    client.flush()
    assert client.scores[0]["name"] == "n" and client.flushed == 1


def test_adapter_delta_counts_only_between_sentinels() -> None:
    loc = l2_sink.adapter_delta_loc()
    assert loc > 0
    # A file with no sentinel section reports zero (Langfuse's real delta).
    empty = SUBTREE / "backend_validation" / "__init__.py"
    assert l2_sink.adapter_delta_loc(empty) == 0


def test_gate_ingestion_round_trips() -> None:
    assert _gate_ingestion_ok(_canonical_run(lambda: _NOW)) is True


# --------------------------------------------------------------------- run_l2
def test_run_l2_ok_writes_adapter_delta(tmp_subtree: Path) -> None:
    result = run_l2(tmp_subtree, _settings(tmp_subtree), run_id="l2-run", now_fn=lambda: _NOW)
    assert result.status == STATUS_OK, result.reason
    import json

    report = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))
    deltas = {entry["backend"]: entry for entry in report["adapter_delta"]}
    assert deltas["langfuse"]["adapter_loc"] == 0  # ships in the harness
    assert deltas["opik"]["adapter_files"] == 1 and deltas["opik"]["adapter_loc"] > 0
    assert report["gate_ingestion_ok"] is True


def test_run_l2_blocks_when_precondition_fails(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend_validation.probes.l2_sink import PreconditionResult

    monkeypatch.setattr(
        "backend_validation.l2_phase.check_precondition",
        lambda: PreconditionResult(
            ok=False, missing=("eval_harness.core.interfaces.ResultSink (absent)",), detail="sink seam absent"
        ),
    )
    result = run_l2(tmp_subtree, _settings(tmp_subtree), run_id="l2-blocked", now_fn=lambda: _NOW)
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    body = Path(result.artifacts[0]).read_text(encoding="utf-8")
    assert "migration-plan scope" in body


def test_run_l2_fails_when_sink_not_conformant(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the Opik score-call sequence to diverge from the harness sink -> FAIL with a
    # recorded mapping gap (the honest "adopting this costs a real adapter" evidence).
    monkeypatch.setattr("backend_validation.l2_phase._opik_scorecalls", lambda _run: [])
    result = run_l2(tmp_subtree, _settings(tmp_subtree), run_id="l2-nonconf", now_fn=lambda: _NOW)
    assert result.status == "FAIL" and "not conformant" in result.reason
    import json

    report = json.loads(Path(result.artifacts[0]).read_text(encoding="utf-8"))
    opik = next(entry for entry in report["adapter_delta"] if entry["backend"] == "opik")
    assert opik["conformance_passed"] == 0 and opik["mapping_gaps"]


def test_run_l2_fails_when_gate_ingestion_breaks(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend_validation.l2_phase._gate_ingestion_ok", lambda _run: False)
    result = run_l2(tmp_subtree, _settings(tmp_subtree), run_id="l2-noingest", now_fn=lambda: _NOW)
    assert result.status == "FAIL" and "evaluate_gate" in result.reason


def test_run_l2_blocks_on_harness_surface_mismatch(tmp_subtree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Finding 7: precondition passes (ResultSink/RunResult/evaluate_gate present) but a deeper
    # symbol the probe imports is gone -> BLOCKED report, never an uncaught ImportError crash.
    def _boom(_now_fn: object) -> object:
        raise ImportError("cannot import name 'LangfuseSink' from 'eval_harness.sinks'")

    monkeypatch.setattr("backend_validation.l2_phase._canonical_run", _boom)
    result = run_l2(tmp_subtree, _settings(tmp_subtree), run_id="l2-surface", now_fn=lambda: _NOW)
    assert result.status == STATUS_BLOCKED and result.exit_code == 3
    assert "harness surface mismatch" in result.reason
    assert "moved or been renamed" in Path(result.artifacts[0]).read_text(encoding="utf-8")
