"""Tests for the audit sampler."""

from __future__ import annotations

import math
import random

import pytest

from agent_core.audit_sampler import (
    AuditConfig,
    inclusion_probability,
    main,
    record_verdict,
    select_for_audit,
    select_for_audit_detailed,
)
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore


def _pending(cid: str, domain: str = "core") -> OutcomeRecord:
    return OutcomeRecord(
        change_id=cid, domain=domain, raw_confidence=0.9, merged_at="2026-01-01T00:00:00+00:00"
    )


def _store(tmp_path, *recs) -> OutcomeStore:
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in recs:
        store.append(r)
    return store


def test_select_honours_per_domain_floor(tmp_path):
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(5)])
    cfg = AuditConfig(base_rate=0.0, per_domain_floor=3)
    picked = select_for_audit(store, cfg, rng=random.Random(0))
    assert len(picked) == 3  # floor met purely by the per-domain floor, base_rate 0


def test_select_base_rate_adds_beyond_floor(tmp_path):
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(20)])
    cfg = AuditConfig(base_rate=1.0, per_domain_floor=0)
    picked = select_for_audit(store, cfg, rng=random.Random(0))
    assert len(picked) == 20  # base_rate 1.0 picks every candidate


def test_select_excludes_already_audited(tmp_path):
    audited = OutcomeRecord(
        change_id="a1",
        domain="core",
        raw_confidence=0.9,
        merged_at="2026-01-01T00:00:00+00:00",
        label=True,
        label_source=LabelSource.HUMAN_AUDIT.value,
        labeled_at="2026-01-02T00:00:00+00:00",
    )
    store = _store(tmp_path, audited, _pending("c1"))
    picked = select_for_audit(
        store, AuditConfig(base_rate=1.0, per_domain_floor=0), rng=random.Random(0)
    )
    assert "a1" not in picked and "c1" in picked


def test_record_verdict_writes_human_audit(tmp_path):
    store = _store(tmp_path, _pending("c1"))
    rec = record_verdict(store, "c1", correct=False, now=None)
    assert rec.label is False and rec.label_source == LabelSource.HUMAN_AUDIT.value
    assert store.resolved()["c1"].label_source == LabelSource.HUMAN_AUDIT.value


def test_record_verdict_unknown_id_raises(tmp_path):
    store = _store(tmp_path, _pending("c1"))
    with pytest.raises(KeyError):
        record_verdict(store, "nope", correct=True)


def test_main_select_and_record(tmp_path, capsys):
    store = _store(tmp_path, _pending("c1"))
    assert (
        main(
            ["--store", str(store.path), "select", "--base-rate", "1.0", "--per-domain-floor", "0"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "c1" in out
    assert main(["--store", str(store.path), "record", "--change-id", "c1", "--correct"]) == 0
    assert store.resolved()["c1"].label is True


# --- selection propensity ----------------------------------------------------
# Recording the probability a change was sampled with is what makes a later
# Horvitz-Thompson / prediction-powered reweighting possible; it cannot be
# reconstructed after the round, so the value must be right at write time.


@pytest.mark.parametrize(
    ("n_candidates", "need_floor", "base_rate", "expected", "why"),
    [
        (5, 5, 0.05, 1.0, "floor covers the pool -> certain"),
        (3, 5, 0.05, 1.0, "floor exceeds the pool -> still certain, never >1"),
        (10, 0, 0.05, 0.05, "no floor left -> pure Bernoulli"),
        (10, 2, 0.5, 0.6, "convex mix: 0.2 + 0.8*0.5"),
        (0, 3, 0.05, 0.0, "empty domain contributes nothing"),
        (10, -1, 0.05, 0.05, "a negative floor clamps to zero, not a negative probability"),
    ],
    ids=["floor-exact", "floor-over", "no-floor", "mixed", "empty", "negative-floor"],
)
def test_inclusion_probability_cases(
    n_candidates: int, need_floor: int, base_rate: float, expected: float, why: str
) -> None:
    assert math.isclose(
        inclusion_probability(n_candidates, need_floor, base_rate), expected, abs_tol=1e-12
    ), why


@pytest.mark.parametrize("n", [1, 3, 17, 50])
@pytest.mark.parametrize("floor", [0, 1, 9, 100])
@pytest.mark.parametrize("rate", [0.0, 0.05, 0.5, 1.0])
def test_inclusion_probability_is_a_valid_probability(n: int, floor: int, rate: float) -> None:
    p = inclusion_probability(n, floor, rate)
    assert 0.0 <= p <= 1.0
    assert p >= rate  # the floor can only ever help a record's odds


def test_inclusion_probability_is_zero_only_when_selection_is_impossible() -> None:
    """The invariant that matters for ``1/p`` is about *selected* records.

    ``p == 0`` is reachable and correct — no floor left and a zero base rate means nobody
    can be drawn — but then nothing is selected, so no stored record ever carries it. Any
    record that *is* selected has ``p > 0`` and a finite weight.
    """
    assert inclusion_probability(10, 0, 0.0) == 0.0  # the only zero case: selection impossible
    for floor, rate in ((1, 0.0), (0, 0.05), (3, 0.5)):
        assert inclusion_probability(10, floor, rate) > 0.0


def test_every_selected_record_has_a_usable_weight(tmp_path) -> None:
    """End-to-end form of the invariant: 1/propensity is finite for everything picked."""
    store = _store(
        tmp_path,
        *[_pending(f"a{i}", domain="core") for i in range(12)],
        *[_pending(f"b{i}", domain="docs") for i in range(3)],
    )
    for rate, floor in ((0.0, 2), (0.05, 0), (0.5, 1), (1.0, 0)):
        picks = select_for_audit_detailed(
            store, AuditConfig(base_rate=rate, per_domain_floor=floor), rng=random.Random(7)
        )
        for sel in picks:
            assert 0.0 < sel.propensity <= 1.0
            assert math.isfinite(1.0 / sel.propensity)


def test_detailed_selection_is_identical_to_the_legacy_call(tmp_path) -> None:
    """Backwards compatibility: adding propensity must not perturb *which* ids are picked.

    The two entry points consume the RNG in the same order, so a shared seed must yield
    the same set — otherwise the sampler silently changed when the field was added.
    """
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(30)])
    cfg = AuditConfig(base_rate=0.3, per_domain_floor=4)
    ids = select_for_audit(store, cfg, rng=random.Random(1234))
    detailed = select_for_audit_detailed(store, cfg, rng=random.Random(1234))
    assert [s.change_id for s in detailed] == ids
    assert ids  # guard against a vacuous pass on an empty selection


def test_detailed_selection_reports_the_domain_propensity(tmp_path) -> None:
    store = _store(
        tmp_path,
        *[_pending(f"a{i}", domain="core") for i in range(10)],
        *[_pending(f"b{i}", domain="docs") for i in range(4)],
    )
    cfg = AuditConfig(base_rate=0.0, per_domain_floor=2)
    picks = select_for_audit_detailed(store, cfg, rng=random.Random(0))
    by_domain = {s.domain: s.propensity for s in picks}
    # The floor over-samples the smaller domain -- exactly the bias 1/p corrects for.
    assert math.isclose(by_domain["core"], 0.2, abs_tol=1e-12)
    assert math.isclose(by_domain["docs"], 0.5, abs_tol=1e-12)
    assert by_domain["docs"] > by_domain["core"]


def test_selection_logs_the_propensity(tmp_path, caplog) -> None:
    store = _store(tmp_path, *[_pending(f"c{i}") for i in range(4)])
    with caplog.at_level("DEBUG", logger="agent_core.audit_sampler"):
        picks = select_for_audit_detailed(
            store, AuditConfig(base_rate=1.0, per_domain_floor=0), rng=random.Random(0)
        )
    assert len(picks) == 4
    assert any("propensity=" in r.message for r in caplog.records)


def test_record_verdict_stores_the_propensity(tmp_path) -> None:
    store = _store(tmp_path, _pending("c1"))
    rec = record_verdict(store, "c1", correct=True, selection_propensity=0.25)
    assert rec.selection_propensity == 0.25
    assert store.resolved()["c1"].selection_propensity == 0.25


def test_record_verdict_propensity_defaults_to_none(tmp_path) -> None:
    """Historical verdicts have no propensity; unknown must stay unknown, not 0 or 1."""
    store = _store(tmp_path, _pending("c1"))
    assert record_verdict(store, "c1", correct=True).selection_propensity is None


@pytest.mark.parametrize(
    "bad",
    [0.0, -0.1, 1.5, float("nan"), float("inf"), float("-inf")],
    ids=["zero", "negative", "above-one", "nan", "inf", "-inf"],
)
def test_record_verdict_rejects_out_of_contract_propensity(tmp_path, bad: float) -> None:
    """A propensity of 0 would make 1/p infinite; NaN/inf would poison every weight."""
    store = _store(tmp_path, _pending("c1"))
    with pytest.raises(ValueError, match="selection_propensity"):
        record_verdict(store, "c1", correct=True, selection_propensity=bad)
    assert store.resolved()["c1"].label is None  # rejected before anything was written


def test_record_verdict_accepts_certain_selection(tmp_path) -> None:
    """p == 1 is legitimate: the per-domain floor takes some records outright."""
    store = _store(tmp_path, _pending("c1"))
    assert record_verdict(store, "c1", correct=True, selection_propensity=1.0).selection_propensity


def test_cli_select_default_output_is_unchanged(tmp_path, capsys) -> None:
    """Existing consumers pipe bare ids; the flag must be opt-in."""
    store = _store(tmp_path, _pending("c1"))
    rc = main(
        ["--store", str(store.path), "select", "--base-rate", "1.0", "--per-domain-floor", "0"]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "c1"


def test_cli_select_with_propensity_emits_two_columns(tmp_path, capsys) -> None:
    store = _store(tmp_path, _pending("c1"))
    rc = main(
        [
            "--store",
            str(store.path),
            "select",
            "--base-rate",
            "1.0",
            "--per-domain-floor",
            "0",
            "--with-propensity",
        ]
    )
    assert rc == 0
    cid, _, prob = capsys.readouterr().out.strip().partition("\t")
    assert cid == "c1"
    assert math.isclose(float(prob), 1.0, abs_tol=1e-9)


def test_cli_record_threads_the_propensity(tmp_path) -> None:
    store = _store(tmp_path, _pending("c1"))
    rc = main(
        [
            "--store",
            str(store.path),
            "record",
            "--change-id",
            "c1",
            "--correct",
            "--selection-propensity",
            "0.05",
        ]
    )
    assert rc == 0
    assert store.resolved()["c1"].selection_propensity == 0.05


def test_cli_bad_propensity_is_a_clean_exit(tmp_path, caplog) -> None:
    """An operator typo must not surface as a traceback (repo convention: exit 2)."""
    store = _store(tmp_path, _pending("c1"))
    with caplog.at_level("ERROR", logger="agent_core.audit_sampler"):
        rc = main(
            [
                "--store",
                str(store.path),
                "record",
                "--change-id",
                "c1",
                "--correct",
                "--selection-propensity",
                "1.5",
            ]
        )
    assert rc == 2
    assert any("selection_propensity" in r.message for r in caplog.records)
    assert store.resolved()["c1"].label is None  # nothing was written


def test_cli_unknown_change_id_still_raises(tmp_path) -> None:
    """Unchanged: an unknown id means the store lacks the record — an integrity problem,
    not a flag typo, so it must stay loud rather than become a tidy exit code."""
    store = _store(tmp_path, _pending("c1"))
    with pytest.raises(KeyError):
        main(["--store", str(store.path), "record", "--change-id", "nope", "--correct"])
