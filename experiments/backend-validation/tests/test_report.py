"""Unit tests for report rendering: marks, deltas, forbidden-heading guard, air-gap table."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend_validation.airgap import AirgapRun, AirgapVerdict, EgressObservation
from backend_validation.observables import Observable, OpOutcome
from backend_validation.registry import load_probes_spec
from backend_validation.report import (
    assert_no_recommendation,
    build_cell_reports,
    render_airgap_report,
    render_claimed_vs_observed,
    score_cell,
    write_report,
)
from backend_validation.rubric import load_rubric

SUBTREE = Path(__file__).resolve().parents[1]
SPEC = load_probes_spec(SUBTREE / "PROBES.yaml")
RULES = load_rubric(SUBTREE / "RUBRIC.md")


def _obs(probe_id: str, backend: str, operation: str, rep: int = 0, **extra: object) -> Observable:
    return Observable(
        probe_id=probe_id,
        cell_id="c",
        backend=backend,
        rep_index=rep,
        ts_utc="t",
        outcome=OpOutcome(operation=operation, status="ok", latency_ms=1.0),
        extra=dict(extra),
    )


def _tracing_pass_obs(backend: str) -> list[Observable]:
    return [
        _obs("l1.tracing.roundtrip", backend, "create_trace"),
        _obs("l1.tracing.roundtrip", backend, "fetch_trace", trace_visible=True),
    ]


# ------------------------------------------------------------------- scoring
def test_score_cell_full_mark_and_match_delta() -> None:
    cell = SPEC.cell("tracing.observability")
    # transcribe a claim so the delta is computable: pretend the matrix claimed full.
    cell_full = cell.__class__(**{**cell.__dict__, "claimed": {"langfuse": "●", "opik": "●"}})
    report = score_cell(cell_full, "langfuse", RULES, _tracing_pass_obs("langfuse"))
    assert report.observed == "●" and report.delta == "match" and report.run_count == 1


def test_score_cell_missing_observables_is_blocked() -> None:
    cell = SPEC.cell("tracing.observability")
    report = score_cell(cell, "langfuse", RULES, [])
    assert report.observed == "BLOCKED" and report.delta == "BLOCKED"


def test_score_cell_human_only_is_not_probed() -> None:
    report = score_cell(SPEC.cell("playground"), "langfuse", RULES, [])
    assert report.observed == "not-probed"


def test_score_cell_overstated_when_claim_exceeds_observed() -> None:
    cell = SPEC.cell("tracing.observability")
    claimed_full = cell.__class__(**{**cell.__dict__, "claimed": {"langfuse": "●", "opik": "●"}})
    # only create_trace succeeds; fetch visibility missing -> partial observed vs full claim.
    partial_obs = [_obs("l1.tracing.roundtrip", "langfuse", "create_trace")]
    report = score_cell(claimed_full, "langfuse", RULES, partial_obs)
    assert report.observed == "◐" and report.delta == "claim-overstated"


def test_flaky_is_flagged_across_reps() -> None:
    cell = SPEC.cell("rag.metrics")  # judge_k3
    obs = [
        _obs("l1.rag.builtin_metric", "langfuse", "run_rag_metric", rep=0, score_in_range=True),
        _obs("l1.rag.builtin_metric", "langfuse", "run_rag_metric", rep=1, score_in_range=False),
        _obs("l1.rag.builtin_metric", "langfuse", "run_rag_metric", rep=2, score_in_range=True),
    ]
    report = score_cell(cell, "langfuse", RULES, obs)
    assert report.flaky is True and report.run_count == 3


# --------------------------------------------------------------- rendering
def test_render_claimed_vs_observed_has_both_columns_and_no_recommendation() -> None:
    reports = build_cell_reports(SPEC, RULES, _tracing_pass_obs("langfuse") + _tracing_pass_obs("opik"))
    text = render_claimed_vs_observed(reports)
    assert "claimed (matrix)" in text and "observed (mechanical)" in text
    assert "tracing.observability" in text
    assert_no_recommendation(text)  # no exception


def test_assert_no_recommendation_rejects_forbidden_headings() -> None:
    for bad in ("## Recommendation", "Our verdict: pick X", "the winner is Langfuse"):
        with pytest.raises(ValueError, match="no recommendation"):
            assert_no_recommendation(bad)


def test_write_report_guards_and_persists(tmp_path: Path) -> None:
    out = write_report(tmp_path / "reports" / "claimed_vs_observed.md", "# Evidence\n\nsafe body\n")
    assert out.is_file() and "safe body" in out.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="no recommendation"):
        write_report(tmp_path / "bad.md", "# Recommendation\npick one\n")


def test_render_airgap_report_dual_scored() -> None:
    leaking = EgressObservation("dns-witness", ("telemetry.example.com",), degraded=True)
    clean = EgressObservation("dns-witness", (), degraded=True)
    verdict = AirgapVerdict(
        backend="langfuse",
        as_shipped=AirgapRun("langfuse", "as-shipped", {}, leaking),
        opt_out=AirgapRun("langfuse", "opt-out", {}, clean),
    )
    text = render_airgap_report([verdict])
    assert "as-shipped" in text and "opt-out" in text
    assert "telemetry.example.com" in text
    assert "| langfuse |" in text and "| yes |" in text  # air-gapped confirmed
    assert_no_recommendation(text)
