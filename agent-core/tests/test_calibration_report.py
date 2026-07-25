"""Tests for agent_core.calibration_report — agent-records calibration report (F-043)."""

from __future__ import annotations

import json

import pytest

from agent_core.calibration_report import (
    analyze_slice,
    build_report,
    main,
    render_json,
    render_markdown,
)
from agent_core.config import ConfigError
from agent_core.domains import is_agent_domain
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from agent_core.report_types import ReportConfig

_TS = "2026-07-20T12:00:00+00:00"


def _seed(cid: str, domain: str, conf: float, av: str | None = None) -> OutcomeRecord:
    return OutcomeRecord(
        cid, domain, conf, _TS, label=None, label_source=None, labeled_at=None, agent_version=av
    )


def _labeled(cid: str, domain: str, conf: float, label: bool, source: LabelSource) -> OutcomeRecord:
    return OutcomeRecord(
        cid, domain, conf, _TS, label=label, label_source=source.value, labeled_at=_TS
    )


def _store(tmp_path, records: list[OutcomeRecord]) -> OutcomeStore:
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in records:
        store.append(r)
    return store


def _mixed_records() -> list[OutcomeRecord]:
    audit = LabelSource.HUMAN_AUDIT
    return [
        # agent domain: 3 human-audits (varying, both classes) + 1 passive
        _seed("c1", "agent-core", 0.8, "claude-code"),
        _labeled("c1", "agent-core", 0.8, True, audit),
        _seed("c2", "agent-core", 0.3, "claude-code"),
        _labeled("c2", "agent-core", 0.3, False, audit),
        _seed("c3", "agent-core", 0.6, "claude-code"),
        _labeled("c3", "agent-core", 0.6, True, audit),
        _seed("c4", "agent-core", 0.5, "claude-code"),
        _labeled("c4", "agent-core", 0.5, True, LabelSource.TIMEOUT_CLEAN),
        # human domain: constant 0.0 predictor, passive labels only
        _seed("h1", "human/eval-harness", 0.0),
        _labeled("h1", "human/eval-harness", 0.0, True, LabelSource.TIMEOUT_CLEAN),
        _seed("h2", "human/eval-harness", 0.0),
        _labeled("h2", "human/eval-harness", 0.0, False, LabelSource.CI_FAILURE),
    ]


# --- helpers ----------------------------------------------------------------
def test_is_agent_domain():
    assert is_agent_domain("agent-core") is True
    assert is_agent_domain("human/agent-core") is False


# --- analyze_slice ----------------------------------------------------------
def test_analyze_slice_non_degenerate():
    s = analyze_slice([(0.8, True), (0.3, False), (0.6, True), (0.2, False)], "x")
    assert s.n == 4
    assert s.n_correct == 2
    assert s.degenerate is None
    assert s.auroc is not None and 0.0 <= s.auroc <= 1.0
    assert s.base_rate is not None and s.base_rate_ci is not None
    assert s.base_rate_ci[0] <= s.base_rate <= s.base_rate_ci[1]
    assert s.abstention_at_target is not None and 0.0 <= s.abstention_at_target <= 1.0


def test_analyze_slice_constant_predictor_is_degenerate():
    s = analyze_slice([(0.5, True), (0.5, False), (0.5, True)], "x")
    assert s.auroc is None
    assert s.degenerate is not None and "constant predictor" in s.degenerate
    # ECE / Brier are still computed even when discrimination is undefined
    assert s.ece is not None and s.brier is not None


def test_analyze_slice_single_class_is_degenerate():
    s = analyze_slice([(0.8, True), (0.6, True), (0.4, True)], "x")
    assert s.auroc is None
    assert s.degenerate is not None and "single outcome class" in s.degenerate
    assert "are correct" in s.degenerate


def test_analyze_slice_single_class_all_incorrect():
    # Covers the "incorrect" arm of the single-class message ternary (invisible to line coverage).
    s = analyze_slice([(0.8, False), (0.6, False), (0.4, False)], "x")
    assert s.auroc is None
    assert s.degenerate is not None and "all 3 labels are incorrect" in s.degenerate


def test_analyze_slice_empty():
    s = analyze_slice([], "x")
    assert s.n == 0
    assert s.degenerate == "no labeled records"
    assert s.auroc is None and s.base_rate is None


# --- build_report -----------------------------------------------------------
def _find(view, label):
    return next(s for s in view.slices if s.label == label)


def test_build_report_agent_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent")
    assert doc.total_records == 12
    assert doc.resolved_records == 6
    assert doc.by_label_source[LabelSource.HUMAN_AUDIT.value] == 3

    primary, diagnostic = doc.views
    assert primary.tau_eligible is True and diagnostic.tau_eligible is False

    agg = _find(primary, "ALL agent domains")
    assert agg.n == 3 and agg.degenerate is None and agg.auroc is not None

    # agent_version recovered by joining the audit record to its seed
    av = _find(primary, "agent_version: claude-code")
    assert av.n == 3

    # diagnostic adds the passive timeout_clean row
    assert _find(diagnostic, "ALL agent domains").n == 4


def test_build_report_human_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="human")
    primary, diagnostic = doc.views
    # no human_audit in human domains -> primary empty
    assert _find(primary, "ALL human domains").degenerate == "no labeled records"
    # diagnostic: two records, both raw_confidence 0.0 -> constant predictor
    diag = _find(diagnostic, "ALL human domains")
    assert diag.n == 2 and diag.auroc is None and "constant predictor" in diag.degenerate


def test_build_report_all_filter(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="all")
    diag = _find(doc.views[1], "ALL all domains")
    assert diag.n == 6  # 4 agent + 2 human labeled


def test_build_report_missing_store(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        doc = build_report(OutcomeStore(tmp_path / "nope.jsonl"), domain_filter="agent")
    assert doc.total_records == 0 and doc.resolved_records == 0
    assert _find(doc.views[0], "ALL agent domains").n == 0
    # A nonexistent store must warn (disambiguates "no data yet" from "wrong --store").
    assert "does not exist" in caplog.text


# --- rendering --------------------------------------------------------------
def test_render_markdown_has_caveat_and_note(tmp_path):
    md = render_markdown(build_report(_store(tmp_path, _mixed_records()), domain_filter="human"))
    assert "Agent-records calibration report" in md
    assert "deterministic proxy" in md  # honest caveat present
    assert "PRIMARY" in md and "DIAGNOSTIC" in md
    assert "constant predictor" in md  # degeneracy surfaced in the note column


def test_render_json_roundtrips(tmp_path):
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent")
    parsed = json.loads(render_json(doc))
    assert parsed["domain_filter"] == "agent"
    assert parsed["views"][0]["tau_eligible"] is True


# --- CLI --------------------------------------------------------------------
def test_cli_markdown_stdout(tmp_path, capsys):
    store = _store(tmp_path, _mixed_records())
    rc = main(["--store", str(store.path), "--domain-filter", "agent"])
    assert rc == 0
    assert "Agent-records calibration report" in capsys.readouterr().out


def test_cli_json_to_file(tmp_path):
    store = _store(tmp_path, _mixed_records())
    out = tmp_path / "report.json"
    rc = main(["--store", str(store.path), "--format", "json", "--output", str(out)])
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["resolved_records"] == 6


def test_cli_rejects_bad_filter(tmp_path):
    with pytest.raises(SystemExit):
        main(["--store", str(tmp_path / "s.jsonl"), "--domain-filter", "bogus"])


# --- ReportConfig (no magic numbers at call sites) --------------------------
def test_report_config_defaults_and_validation():
    cfg = ReportConfig()
    assert (cfg.n_bins, cfg.risk_target, cfg.z) == (10, 0.05, 1.96)
    # Range violations plus non-finite values (NaN/inf slip past bare range checks — e.g.
    # `inf > 0` is True — so the math.isfinite guards must reject them).
    for bad in (
        dict(n_bins=0),
        dict(risk_target=1.5),
        dict(z=0.0),
        dict(risk_target=float("nan")),
        dict(risk_target=float("inf")),
        dict(z=float("inf")),
        dict(z=float("nan")),
    ):
        with pytest.raises(ConfigError):
            ReportConfig(**bad)


def test_report_config_flags_are_load_bearing():
    # A mutant that hardcoded ReportConfig() and ignored the flags must fail: assert each knob
    # produces an observable effect, not just rc == 0.
    data = [(0.9, True), (0.7, True), (0.6, False), (0.3, False), (0.2, True)]
    assert analyze_slice(data, "x", cfg=ReportConfig(risk_target=0.1)).risk_target == 0.1
    narrow = analyze_slice(data, "x", cfg=ReportConfig(z=1.0)).base_rate_ci
    wide = analyze_slice(data, "x", cfg=ReportConfig(z=2.58)).base_rate_ci
    assert narrow is not None and wide is not None
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])  # larger z -> wider Wilson CI
    ece_coarse = analyze_slice(data, "x", cfg=ReportConfig(n_bins=2)).ece
    ece_fine = analyze_slice(data, "x", cfg=ReportConfig(n_bins=20)).ece
    assert ece_coarse != ece_fine  # bin count changes the ECE partition


def test_cli_honours_report_config_flags(tmp_path, capsys):
    store = _store(tmp_path, _mixed_records())
    rc = main(["--store", str(store.path), "--n-bins", "5", "--risk-target", "0.1", "--z", "1.64"])
    assert rc == 0
    out = capsys.readouterr().out
    # --risk-target must reach the rendered abstain@risk column (proves the flag is threaded,
    # not merely accepted): non-degenerate agent rows render `@0.1`, never the `@0.05` default.
    assert "@0.1" in out and "@0.05" not in out


def test_cli_bad_config_is_clean_exit(tmp_path):
    # A bad --n-bins is an operator error: clean exit 2 + logged message, not a traceback.
    store = _store(tmp_path, _mixed_records())
    rc = main(["--store", str(store.path), "--n-bins", "0"])
    assert rc == 2


# --- estimator selection (wilson / ppi++) ------------------------------------
# The estimator is a *reporting* choice only. The gate keeps using Wilson, so the
# tests below pin both that the default path is untouched and that ppi++ is additive.


def test_estimator_defaults_to_wilson() -> None:
    assert ReportConfig().estimator == "wilson"


def test_estimator_rejects_an_unknown_name() -> None:
    with pytest.raises(ConfigError, match="estimator"):
        ReportConfig(estimator="bootstrap")


def test_default_report_carries_no_ppi(tmp_path) -> None:
    """Byte-for-byte the previous behaviour: no PPI computed unless asked for."""
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent")
    assert doc.estimator == "wilson"
    assert all(s.ppi is None for v in doc.views for s in v.slices)


def test_ppi_estimator_attaches_an_estimate_to_every_slice(tmp_path) -> None:
    cfg = ReportConfig(estimator="ppi++")
    doc = build_report(_store(tmp_path, _mixed_records()), domain_filter="agent", cfg=cfg)
    assert doc.estimator == "ppi++"
    populated = [s for v in doc.views for s in v.slices if s.n > 0]
    assert populated and all(s.ppi is not None for s in populated)


def test_ppi_never_changes_the_wilson_columns(tmp_path) -> None:
    """Dual-report means *adding* a column, never silently altering the existing one."""
    records = _mixed_records()
    base = build_report(_store(tmp_path, records), domain_filter="agent")
    dual = build_report(
        _store(tmp_path, records), domain_filter="agent", cfg=ReportConfig(estimator="ppi++")
    )
    for v_base, v_dual in zip(base.views, dual.views, strict=True):
        for s_base, s_dual in zip(v_base.slices, v_dual.slices, strict=True):
            assert s_base.base_rate_ci == s_dual.base_rate_ci
            assert (s_base.n, s_base.n_correct, s_base.ece) == (
                s_dual.n,
                s_dual.n_correct,
                s_dual.ece,
            )


def test_markdown_renders_both_estimators(tmp_path) -> None:
    cfg = ReportConfig(estimator="ppi++")
    md = render_markdown(
        build_report(_store(tmp_path, _mixed_records()), domain_filter="agent", cfg=cfg)
    )
    assert "base rate [Wilson 95%]" in md
    assert "PPI++ 95%" in md
    assert "var-reduction" in md
    assert "does **not** change" in md  # the honesty note about the gate


def test_markdown_default_has_no_ppi_column(tmp_path) -> None:
    md = render_markdown(build_report(_store(tmp_path, _mixed_records()), domain_filter="agent"))
    assert "PPI++" not in md


def test_analyze_slice_unlabeled_pool_is_ignored_by_wilson() -> None:
    """The extra argument must be inert on the default path."""
    pairs = [(0.9, True), (0.8, False), (0.7, True)]
    without = analyze_slice(pairs, "s")
    with_pool = analyze_slice(pairs, "s", unlabeled_proxy=[0.1, 0.2, 0.3])
    assert without == with_pool


def test_analyze_slice_ppi_uses_the_unlabeled_pool() -> None:
    pairs = [(i / 10, i % 2 == 0) for i in range(10)]
    cfg = ReportConfig(estimator="ppi++")
    est = analyze_slice(pairs, "s", cfg=cfg, unlabeled_proxy=[i / 10 for i in range(100)]).ppi
    assert est is not None
    assert est.n_labeled == 10 and est.n_unlabeled == 100


def test_ppi_falls_back_to_wilson_on_a_degenerate_slice() -> None:
    """A single-class slice must not report a tighter interval than Wilson."""
    pairs = [(0.9, True)] * 6
    cfg = ReportConfig(estimator="ppi++")
    report = analyze_slice(pairs, "s", cfg=cfg, unlabeled_proxy=[0.9] * 50)
    assert report.ppi is not None and report.ppi.degenerate is not None
    assert report.base_rate_ci is not None
    assert abs(report.ppi.lo - report.base_rate_ci[0]) < 1e-12


def test_cli_accepts_the_estimator_flag(tmp_path, capsys) -> None:
    store = _store(tmp_path, _mixed_records())
    assert main(["--store", str(store.path), "--estimator", "ppi++"]) == 0
    assert "PPI++ 95%" in capsys.readouterr().out


def test_cli_rejects_an_unknown_estimator(tmp_path) -> None:
    store = _store(tmp_path, _mixed_records())
    with pytest.raises(SystemExit):
        main(["--store", str(store.path), "--estimator", "jackknife"])


def test_cli_json_includes_the_estimator(tmp_path) -> None:
    store = _store(tmp_path, _mixed_records())
    out = tmp_path / "r.json"
    rc = main(
        [
            "--store",
            str(store.path),
            "--format",
            "json",
            "--estimator",
            "ppi++",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["estimator"] == "ppi++"


def test_public_names_survive_the_module_split() -> None:
    """The report was split into analysis/types/rendering; imports must not break.

    External callers (and older code) import these from `calibration_report`; the split
    is an internal layering change, so every name must still resolve from there.
    """
    import agent_core.calibration_report as cr
    from agent_core import calibration_report_render, report_types

    assert cr.ReportConfig is report_types.ReportConfig
    assert cr.SliceReport is report_types.SliceReport
    assert cr.ReportDoc is report_types.ReportDoc
    assert cr.View is report_types.View
    assert cr.render_markdown is calibration_report_render.render_markdown
    assert cr.render_json is calibration_report_render.render_json
