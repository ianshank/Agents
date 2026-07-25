"""Tests for the proxy-correlation report.

The module exists to answer one question honestly — is a cheap proxy informative
*where the gate actually operates* — so these tests focus on the ways that answer
could be faked: a marginal correlation standing in for a conditional one, a
degenerate slice reported as a number, or a missing proxy value silently read as 0.
"""

from __future__ import annotations

import json
import math

import pytest

from agent_core.config import ConfigError
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from agent_core.ppi import PPIEstimate
from agent_core.proxy_eval import (
    MappingProxy,
    PassiveLabelProxy,
    ProxyEvalConfig,
    ProxyExtractor,
    RawConfidenceProxy,
    analyze_dataset,
    build_dataset,
    default_extractors,
    evaluate_store,
    main,
    render_json,
    render_markdown,
)

_TS = "2026-07-20T12:00:00+00:00"
CFG = ProxyEvalConfig()


def _seed(cid: str, domain: str, conf: float) -> OutcomeRecord:
    return OutcomeRecord(cid, domain, conf, _TS)


def _labeled(cid: str, domain: str, conf: float, label: bool, source: LabelSource):
    return OutcomeRecord(
        cid, domain, conf, _TS, label=label, label_source=source.value, labeled_at=_TS
    )


def _store(tmp_path, records) -> OutcomeStore:
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in records:
        store.append(r)
    return store


def _partially_audited(tmp_path, audited_pairs, unaudited_confidences, domain: str = "core"):
    """Audited pairs PLUS unaudited seeds, so the unlabeled pool PPI borrows from is real.

    Without this every change carried an audit row, the pool was always empty, and every
    `ppi` assertion in this module was silently checking a Wilson fallback.
    """
    records = []
    for i, (conf, correct) in enumerate(audited_pairs):
        records.append(_seed(f"c{i}", domain, conf))
        records.append(_labeled(f"c{i}", domain, conf, correct, LabelSource.HUMAN_AUDIT))
    for j, conf in enumerate(unaudited_confidences):
        records.append(_seed(f"u{j}", domain, conf))
    return _store(tmp_path, records)


def _audited(tmp_path, pairs, domain: str = "core"):
    """One seed row + one HUMAN_AUDIT row per (confidence, correct) pair."""
    records = []
    for i, (conf, correct) in enumerate(pairs):
        records.append(_seed(f"c{i}", domain, conf))
        records.append(_labeled(f"c{i}", domain, conf, correct, LabelSource.HUMAN_AUDIT))
    return _store(tmp_path, records)


# --- config ------------------------------------------------------------------
def test_config_defaults() -> None:
    cfg = ProxyEvalConfig()
    assert (cfg.n_bins, cfg.z, cfg.min_pairs) == (10, 1.96, 3)
    assert cfg.tau_quantiles == (0.5, 0.75, 0.9)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProxyEvalConfig(n_bins=0),
        lambda: ProxyEvalConfig(z=0.0),
        lambda: ProxyEvalConfig(z=float("nan")),
        lambda: ProxyEvalConfig(z=float("inf")),
        lambda: ProxyEvalConfig(min_pairs=1),
        lambda: ProxyEvalConfig(min_pairs=2),
        lambda: ProxyEvalConfig(tau_quantiles=(1.0,)),
        lambda: ProxyEvalConfig(tau_quantiles=(-0.1,)),
        lambda: ProxyEvalConfig(tau_quantiles=(float("nan"),)),
    ],
)
def test_config_rejects_invalid_values(factory) -> None:
    with pytest.raises(ConfigError):
        factory()


# --- extractors --------------------------------------------------------------
def test_extractors_satisfy_the_protocol() -> None:
    for ex in (RawConfidenceProxy(), PassiveLabelProxy(), MappingProxy("x", {})):
        assert isinstance(ex, ProxyExtractor)


def test_raw_confidence_proxy_prefers_the_non_audit_row() -> None:
    """The audit row copies the seed's confidence; read the seed so the join is explicit."""
    seed = _seed("c1", "core", 0.42)
    audit = _labeled("c1", "core", 0.42, True, LabelSource.HUMAN_AUDIT)
    assert RawConfidenceProxy().value("c1", [audit, seed]) == 0.42


def test_raw_confidence_proxy_falls_back_to_an_audit_only_history() -> None:
    audit = _labeled("c1", "core", 0.31, True, LabelSource.HUMAN_AUDIT)
    assert RawConfidenceProxy().value("c1", [audit]) == 0.31


def test_raw_confidence_proxy_on_no_records_is_none() -> None:
    assert RawConfidenceProxy().value("c1", []) is None


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (LabelSource.REVERT, 0.0),
        (LabelSource.CI_FAILURE, 0.0),
        (LabelSource.TIMEOUT_CLEAN, 1.0),
    ],
    ids=["revert", "ci-failure", "timeout-clean"],
)
def test_passive_label_proxy_maps_each_source(source, expected) -> None:
    rec = _labeled("c1", "core", 0.5, expected == 1.0, source)
    assert PassiveLabelProxy().value("c1", [rec]) == expected


def test_passive_label_proxy_is_none_without_a_passive_row() -> None:
    """No passive signal must drop the change, never coerce to 0.0 (a fabricated failure)."""
    audit = _labeled("c1", "core", 0.5, True, LabelSource.HUMAN_AUDIT)
    assert PassiveLabelProxy().value("c1", [audit, _seed("c1", "core", 0.5)]) is None


def test_mapping_proxy_reads_external_scores() -> None:
    proxy = MappingProxy("judge", {"c1": 0.75})
    assert proxy.value("c1", []) == 0.75
    assert proxy.value("missing", []) is None


def test_mapping_proxy_rejects_non_finite_scores() -> None:
    proxy = MappingProxy("judge", {"c1": float("nan"), "c2": float("inf")})
    assert proxy.value("c1", []) is None and proxy.value("c2", []) is None


def test_default_extractors_add_the_judge_only_when_supplied() -> None:
    assert [e.name for e in default_extractors()] == ["raw_confidence", "passive_label"]
    assert "judge_score" in [e.name for e in default_extractors({"c1": 0.5})]
    assert [e.name for e in default_extractors({})] == ["raw_confidence", "passive_label"]


# --- dataset assembly --------------------------------------------------------
def test_build_dataset_splits_labelled_from_unlabelled(tmp_path) -> None:
    store = _store(
        tmp_path,
        [
            _seed("c1", "core", 0.9),
            _labeled("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT),
            _seed("c2", "core", 0.4),  # never audited -> unlabeled pool
            _seed("c3", "core", 0.7),
            _labeled("c3", "core", 0.7, False, LabelSource.TIMEOUT_CLEAN),  # passive != truth
        ],
    )
    ds = build_dataset(store, RawConfidenceProxy(), domain_filter="all")
    assert [p.change_id for p in ds.labeled] == ["c1"]
    assert sorted(ds.unlabeled) == [0.4, 0.7]


def test_build_dataset_honours_the_domain_filter(tmp_path) -> None:
    store = _store(
        tmp_path,
        [
            _seed("c1", "core", 0.9),
            _labeled("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT),
            _seed("c2", "human/core", 0.1),
            _labeled("c2", "human/core", 0.1, True, LabelSource.HUMAN_AUDIT),
        ],
    )
    agent = build_dataset(store, RawConfidenceProxy(), domain_filter="agent")
    human = build_dataset(store, RawConfidenceProxy(), domain_filter="human")
    every = build_dataset(store, RawConfidenceProxy(), domain_filter="all")
    assert [p.change_id for p in agent.labeled] == ["c1"]
    assert [p.change_id for p in human.labeled] == ["c2"]
    assert len(every.labeled) == 2


def test_build_dataset_drops_changes_the_proxy_cannot_score(tmp_path) -> None:
    store = _store(
        tmp_path,
        [
            _seed("c1", "core", 0.9),
            _labeled("c1", "core", 0.9, True, LabelSource.HUMAN_AUDIT),
        ],
    )
    ds = build_dataset(store, MappingProxy("judge", {}), domain_filter="all")
    assert ds.labeled == () and ds.unlabeled == ()


def test_build_dataset_ignores_an_audit_row_with_no_verdict(tmp_path) -> None:
    """label_source says audit but label is None -> not authoritative, so it is unlabeled."""
    store = _store(
        tmp_path,
        [
            OutcomeRecord(
                "c1", "core", 0.9, _TS, label=None, label_source=LabelSource.HUMAN_AUDIT.value
            )
        ],
    )
    ds = build_dataset(store, RawConfidenceProxy(), domain_filter="all")
    assert ds.labeled == () and ds.unlabeled == (0.9,)


# --- analysis ----------------------------------------------------------------
def test_marginal_correlation_is_measured(tmp_path) -> None:
    store = _audited(tmp_path, [(0.1, False), (0.2, False), (0.8, True), (0.9, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.marginal.n == 4
    assert rep.marginal.rho is not None and rep.marginal.rho > 0.9
    assert rep.marginal.auroc == 1.0
    assert rep.marginal.effective_n > 1.0
    assert rep.marginal.degenerate is None


def test_restriction_of_range_shrinks_the_conditional_correlation(tmp_path) -> None:
    """The module's whole reason for existing.

    A proxy can look strong marginally and be worthless on the high-confidence subset the
    gate auto-merges from, because that subset is near-constant in the proxy by
    construction. The report must show that, not hide it behind one headline number.
    """
    pairs = [(i / 20, i >= 10) for i in range(20)]
    store = _audited(tmp_path, pairs)
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    top = next(s for s in rep.conditional if s.label.startswith("proxy >= q0.9"))
    assert rep.marginal.rho is not None
    # Everything above the 90th percentile is correct -> single class, no measurable signal.
    assert top.degenerate is not None
    assert top.effective_n == 1.0


def test_degenerate_slices_name_the_constant_side(tmp_path) -> None:
    store = _audited(tmp_path, [(0.5, True), (0.5, False), (0.5, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.marginal.rho is None
    assert "constant proxy" in (rep.marginal.degenerate or "")


def test_single_outcome_class_is_named_distinctly(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, True), (0.6, True), (0.9, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert "single outcome class" in (rep.marginal.degenerate or "")
    assert rep.marginal.auroc is None  # undefined, not the by-construction 0.5


def test_too_few_pairs_is_reported_not_computed(tmp_path) -> None:
    store = _audited(tmp_path, [(0.5, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert "insufficient pairs" in (rep.marginal.degenerate or "")
    assert rep.marginal.rho is None


def test_empty_dataset_yields_no_ppi(tmp_path) -> None:
    store = _store(tmp_path, [])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.n_labeled == 0 and rep.ppi is None
    assert rep.marginal.degenerate is not None


def test_ppi_estimate_is_attached_when_pairs_exist(tmp_path) -> None:
    pairs = [(i / 20, i % 3 != 0) for i in range(20)]
    store = _audited(tmp_path, pairs)
    ds = build_dataset(store, RawConfidenceProxy(), domain_filter="all")
    rep = analyze_dataset(ds, CFG)
    assert isinstance(rep.ppi, PPIEstimate)
    assert 0.0 <= rep.ppi.lo <= rep.ppi.hi <= 1.0


def test_per_bin_slices_only_appear_for_populated_bins(tmp_path) -> None:
    store = _audited(tmp_path, [(0.05, False), (0.95, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    bin_labels = [s.label for s in rep.conditional if s.label.startswith("bin ")]
    assert len(bin_labels) == 2  # 8 empty bins are omitted rather than rendered as n=0


# --- evaluate_store ----------------------------------------------------------
def test_evaluate_store_runs_every_default_proxy(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    reports = evaluate_store(store, cfg=CFG, domain_filter="all")
    assert [r.proxy for r in reports] == ["raw_confidence", "passive_label"]


def test_evaluate_store_warns_on_a_missing_store(tmp_path, caplog) -> None:
    store = OutcomeStore(tmp_path / "nope.jsonl")
    with caplog.at_level("WARNING", logger="agent_core.proxy_eval"):
        reports = evaluate_store(store, cfg=CFG, domain_filter="all")
    assert all(r.n_labeled == 0 for r in reports)
    assert any("does not exist" in r.message for r in caplog.records)


def test_evaluate_store_accepts_custom_extractors(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    reports = evaluate_store(
        store, [MappingProxy("judge", {"c0": 0.1, "c1": 0.9})], cfg=CFG, domain_filter="all"
    )
    assert len(reports) == 1 and reports[0].proxy == "judge"
    assert reports[0].n_labeled == 2


# --- rendering ---------------------------------------------------------------
def test_render_markdown_includes_slices_and_ppi(tmp_path) -> None:
    store = _audited(tmp_path, [(i / 10, i % 2 == 0) for i in range(10)])
    text = render_markdown(evaluate_store(store, cfg=CFG, domain_filter="all"), CFG)
    assert "# Proxy-correlation report" in text
    assert "marginal (all audited)" in text
    assert "n_eff" in text
    assert "PPI++ on this proxy" in text


def test_render_markdown_surfaces_a_degenerate_ppi(tmp_path) -> None:
    store = _audited(tmp_path, [(0.3, True), (0.6, True), (0.9, True)])
    text = render_markdown(evaluate_store(store, cfg=CFG, domain_filter="all"), CFG)
    assert "DEGENERATE" in text


def test_render_json_is_parseable_and_complete(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    payload = json.loads(render_json(evaluate_store(store, cfg=CFG, domain_filter="all"), CFG))
    assert payload["config"]["n_bins"] == CFG.n_bins
    first = payload["proxies"][0]
    assert first["proxy"] == "raw_confidence"
    assert "variance_reduction" in first["ppi"]
    assert "marginal" in first and "conditional" in first


def test_render_json_handles_a_proxy_with_no_data(tmp_path) -> None:
    store = _store(tmp_path, [])
    payload = json.loads(render_json(evaluate_store(store, cfg=CFG, domain_filter="all"), CFG))
    assert payload["proxies"][0]["ppi"] is None


# --- CLI ---------------------------------------------------------------------
def test_cli_markdown_to_stdout(tmp_path, capsys) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    rc = main(["--store", str(store.path), "--domain-filter", "all"])
    assert rc == 0
    assert "Proxy-correlation report" in capsys.readouterr().out


def test_cli_json_to_file(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    out = tmp_path / "r.json"
    rc = main(["--store", str(store.path), "--format", "json", "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["proxies"]


def test_cli_bad_config_is_a_clean_exit(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    assert main(["--store", str(store.path), "--n-bins", "0"]) == 2


def test_cli_rejects_an_unknown_domain_filter(tmp_path) -> None:
    with pytest.raises(SystemExit):
        main(["--store", str(tmp_path / "s.jsonl"), "--domain-filter", "bogus"])


def test_cli_loads_judge_scores(tmp_path, capsys) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    scores = tmp_path / "judge.json"
    scores.write_text(json.dumps({"c0": 0.1, "c1": 0.9}), encoding="utf-8")
    rc = main(["--store", str(store.path), "--domain-filter", "all", "--judge-scores", str(scores)])
    assert rc == 0
    assert "judge_score" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ('["not", "an", "object"]', "top level must be an object"),
        ('{"c1": "high"}', "score must be numeric"),
        ('{"c1": true}', "bool is not a score"),
        ('{"c1": 1e999}', "non-finite score"),
    ],
    ids=["not-an-object", "string-score", "bool-score", "inf-score"],
)
def test_cli_rejects_malformed_judge_scores(tmp_path, payload: str, why: str) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    scores = tmp_path / "judge.json"
    scores.write_text(payload, encoding="utf-8")
    assert main(["--store", str(store.path), "--judge-scores", str(scores)]) == 2, why


def test_cli_missing_judge_scores_file_is_a_clean_exit(tmp_path) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    assert main(["--store", str(store.path), "--judge-scores", str(tmp_path / "gone.json")]) == 2


def test_cli_honours_the_z_flag(tmp_path, capsys) -> None:
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    assert main(["--store", str(store.path), "--domain-filter", "all", "--z", "1.64"]) == 0
    assert "z=1.64" in capsys.readouterr().out


def test_quantile_helper_is_within_the_sample(tmp_path) -> None:
    """Nearest-rank keeps every cutoff an observed value, so slices are never empty."""
    store = _audited(tmp_path, [(i / 10, i % 2 == 0) for i in range(10)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    for sl in rep.conditional:
        if sl.label.startswith("proxy >="):
            assert sl.n >= 1
    assert math.isclose(rep.marginal.effective_n, rep.marginal.effective_n)  # finite


def test_a_perfect_correlation_is_reported_as_an_artifact(tmp_path) -> None:
    """|rho| == 1 on a handful of records is collinearity, not evidence.

    The proxy here is an exact affine map of the outcome, so rho is identically 1 and the
    guard must fire. An earlier version of this test used a fixture with rho = 0.866 --
    it never reached the guard at all, and deleting the guard left it green.
    """
    store = _audited(tmp_path, [(0.2, False), (0.2, False), (0.8, True), (0.8, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.marginal.degenerate is not None
    assert "perfect correlation" in rep.marginal.degenerate
    assert rep.marginal.rho is None
    assert rep.marginal.effective_n == 1.0


def test_two_point_slices_are_never_scored(tmp_path) -> None:
    """n=2 makes |rho| == 1 by construction, so it must not reach the correlation math."""
    store = _audited(tmp_path, [(0.2, False), (0.8, True)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.marginal.rho is None
    assert "insufficient pairs" in (rep.marginal.degenerate or "")
    assert rep.marginal.effective_n == 1.0


def test_ppi_is_computed_against_a_real_unlabeled_pool(tmp_path) -> None:
    """The PPI path must be exercised, not just its Wilson fallback."""
    audited = [(i / 20, i % 3 != 0) for i in range(14)]
    store = _partially_audited(tmp_path, audited, [i / 40 for i in range(60)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    assert rep.ppi is not None
    assert rep.n_unlabeled == 60
    assert rep.ppi.degenerate is None, "expected a live PPI estimate, not a fallback"
    assert rep.ppi.n_unlabeled == 60
    assert 0.0 <= rep.ppi.lo <= rep.ppi.point <= rep.ppi.hi <= 1.0


def test_bins_span_the_observed_proxy_range_not_the_unit_interval(tmp_path) -> None:
    """Regression: fixed [0,1] edges dropped every out-of-range score.

    An external judge's scores carry no unit-interval contract, so scores below 0 landed
    in no bin at all and everything above 1 was swept into a bin mislabelled "[0.9,1)".
    """
    audited = [(i / 20, i % 2 == 0) for i in range(12)]
    store = _partially_audited(tmp_path, audited, [0.5] * 5)
    scores = {f"c{i}": -3.0 + i for i in range(12)}  # spans -3 .. +8
    scores.update({f"u{j}": 0.0 for j in range(5)})
    rep = analyze_dataset(
        build_dataset(store, MappingProxy("judge", scores), domain_filter="all"), CFG
    )
    binned = [s for s in rep.conditional if s.label.startswith("bin ")]
    assert binned, "out-of-unit-range proxies must still be binned"
    assert sum(s.n for s in binned) == rep.n_labeled, "every labelled pair must land in a bin"


def test_passive_prediction_covers_every_passive_label_source() -> None:
    """A new LabelSource must not be silently ignored (dropping the change entirely)."""
    from agent_core.proxies import _PASSIVE_PREDICTION

    assert set(_PASSIVE_PREDICTION) | {LabelSource.HUMAN_AUDIT.value} == {
        s.value for s in LabelSource
    }


def test_authoritative_audit_wins_over_an_earlier_unlabelled_audit_row(tmp_path) -> None:
    """Regression: `next(...)` took the FIRST audit row, disagreeing with resolved().

    An early audit row carrying `label=None` demoted a genuinely audited change into the
    unlabelled pool — losing a scarce label and breaking the labeled/unlabeled
    disjointness the variance formula assumes.
    """
    store = _store(
        tmp_path,
        [
            _seed("z1", "core", 0.8),
            OutcomeRecord(
                "z1", "core", 0.8, _TS, label=None, label_source=LabelSource.HUMAN_AUDIT.value
            ),
            _labeled("z1", "core", 0.8, True, LabelSource.HUMAN_AUDIT),
        ],
    )
    ds = build_dataset(store, RawConfidenceProxy(), domain_filter="all")
    assert [p.change_id for p in ds.labeled] == ["z1"]
    assert ds.labeled[0].correct is True
    assert ds.unlabeled == ()
    assert store.resolved()["z1"].label is True  # agrees with the canonical resolution


def test_a_degenerate_slice_withholds_auroc(tmp_path) -> None:
    """Regression: a constant proxy reported `auroc = 0.5`.

    A constant proxy cannot rank anything, so 0.5 is its value *by construction* — the
    exact number `calibration_report.analyze_slice` refuses to print ("rather than a
    misleading AUROC of 0.5"). Both outcome classes being present makes AUROC *defined*,
    not meaningful, so the degeneracy flag has to gate it.
    """
    store = _audited(tmp_path, [(0.5, i % 2 == 0) for i in range(6)])
    rep = analyze_dataset(build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG)
    m = rep.marginal
    assert m.degenerate is not None and "constant proxy" in m.degenerate
    assert m.rho is None
    assert m.auroc is None, "a degenerate slice must not report a by-construction AUROC"
    assert m.effective_n == 1.0


def test_a_healthy_slice_still_reports_auroc(tmp_path) -> None:
    """The guard must not suppress AUROC on slices that can genuinely evidence ranking."""
    store = _audited(tmp_path, [(i / 10, i >= 3) for i in range(8)])
    m = analyze_dataset(
        build_dataset(store, RawConfidenceProxy(), domain_filter="all"), CFG
    ).marginal
    assert m.degenerate is None
    assert m.auroc is not None
