"""Tests for F-025 — A/B eval campaigns with statistical significance."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from eval_harness.campaign import (
    CampaignRecord,
    CampaignStore,
    Decision,
    analyze,
    pass_counts,
    record_run,
)
from eval_harness.cli import main as cli_main
from eval_harness.config.models import ABCampaignConfig, EvalConfig
from eval_harness.version import SCHEMA_VERSION

FIXED = datetime(2026, 6, 30, tzinfo=timezone.utc)


def _items(n: int) -> list[dict]:
    # Every item: arm "hi" (echo 'good') passes; arm "lo" (echo 'bad') fails.
    return [{"id": str(i), "inputs": {"good": "x", "bad": "y"}, "expected": "x"} for i in range(n)]


def _config(n_items: int, *, min_sample: int = 30, hi_is_b: bool = True) -> EvalConfig:
    hi = {"name": "hi", "target": {"type": "echo", "params": {"output_key": "good"}}}
    lo = {"name": "lo", "target": {"type": "echo", "params": {"output_key": "bad"}}}
    arm_a, arm_b = (lo, hi) if hi_is_b else (hi, lo)
    return EvalConfig(
        schema_version=SCHEMA_VERSION,
        run={"name": "camp"},
        dataset={"type": "inline", "params": {"items": _items(n_items)}},
        target={"type": "echo", "params": {}},
        scorers=[{"type": "exact_match", "params": {}}],
        ab_campaign={
            "campaign_id": "c1",
            "arm_a": arm_a,
            "arm_b": arm_b,
            "score": "exact_match",
            "min_sample": min_sample,
        },
    )


# --- config + primitives -----------------------------------------------------


def test_arms_must_be_distinct():
    arm = {"name": "x", "target": {"type": "echo"}}
    with pytest.raises(ValueError, match="distinct"):
        ABCampaignConfig(campaign_id="c", arm_a=arm, arm_b=arm, score="s")


def test_store_accumulates_totals(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    store.append(CampaignRecord("c1", "hi", "exact_match", 10, 10, FIXED.isoformat()))
    store.append(CampaignRecord("c1", "hi", "exact_match", 5, 5, FIXED.isoformat()))
    store.append(CampaignRecord("c1", "lo", "exact_match", 0, 8, FIXED.isoformat()))
    store.append(CampaignRecord("other", "hi", "exact_match", 99, 99, FIXED.isoformat()))
    assert store.totals("c1", "hi") == (15, 15)
    assert store.totals("c1", "lo") == (0, 8)
    assert store.totals("c1", "missing") == (0, 0)


def test_record_run_writes_per_arm_counts(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    recs = record_run(store, _config(30), langfuse_client=None, now=FIXED)
    by_arm = {r.arm: r for r in recs}
    assert by_arm["hi"].successes == 30 and by_arm["hi"].n == 30
    assert by_arm["lo"].successes == 0 and by_arm["lo"].n == 30


def test_record_run_requires_config(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = EvalConfig(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {"items": _items(1)}},
        target={"type": "echo", "params": {}},
    )
    with pytest.raises(ValueError, match="ab_campaign"):
        record_run(store, cfg)


def test_pass_counts_matches_pass_rate_semantics():
    # success = passed is True; denominator = passed is not None (None ignored).
    from datetime import datetime, timezone

    from eval_harness.core.types import (
        EvalItem,
        ItemResult,
        RunResult,
        ScoreResult,
        TargetOutput,
    )

    def _item(passed: bool | None) -> ItemResult:
        return ItemResult(
            item=EvalItem(id="i", inputs={}),
            output=TargetOutput(output=None),
            scores=[ScoreResult("exact_match", value=1.0 if passed else 0.0, passed=passed)],
        )

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    run = RunResult(
        run_id="r",
        config_name="c",
        items=[_item(True), _item(False), _item(None), _item(True)],
        aggregate={},
        started_at=now,
        finished_at=now,
    )
    assert pass_counts(run, "exact_match") == (2, 3)  # None ignored in denominator
    assert pass_counts(run, "absent") == (0, 0)


# --- analyze decisions -------------------------------------------------------


def test_decision_b_better_when_powered_and_separated(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = _config(30, min_sample=30, hi_is_b=True)
    record_run(store, cfg, now=FIXED)
    result = analyze(store, cfg.ab_campaign)
    assert result.decision is Decision.B_BETTER
    assert result.delta == 1.0  # hi(b)=1.0 - lo(a)=0.0


def test_decision_a_better_when_arm_a_is_hi(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = _config(30, min_sample=30, hi_is_b=False)
    record_run(store, cfg, now=FIXED)
    result = analyze(store, cfg.ab_campaign)
    assert result.decision is Decision.A_BETTER


def test_decision_cant_tell_below_power(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = _config(5, min_sample=30)  # only 5 per arm < 30
    record_run(store, cfg, now=FIXED)
    result = analyze(store, cfg.ab_campaign)
    assert result.decision is Decision.CANT_TELL


def test_decision_no_difference_when_overlapping(tmp_path):
    # Both arms echo 'good' -> identical 30/30 -> overlapping CIs -> no_difference.
    store = CampaignStore(tmp_path / "s.jsonl")
    good = {"type": "echo", "params": {"output_key": "good"}}
    cfg = EvalConfig(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {"items": _items(30)}},
        target={"type": "echo", "params": {}},
        scorers=[{"type": "exact_match", "params": {}}],
        ab_campaign={
            "campaign_id": "c1",
            "arm_a": {"name": "a", "target": good},
            "arm_b": {"name": "b", "target": good},
            "score": "exact_match",
            "min_sample": 30,
        },
    )
    record_run(store, cfg, now=FIXED)
    assert analyze(store, cfg.ab_campaign).decision is Decision.NO_DIFFERENCE


def test_accumulation_across_runs_reaches_power(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = _config(10, min_sample=30)  # 10/run, below power after one run
    record_run(store, cfg, now=FIXED)
    assert analyze(store, cfg.ab_campaign).decision is Decision.CANT_TELL
    record_run(store, cfg, now=FIXED)
    record_run(store, cfg, now=FIXED)  # now 30 per arm -> powered
    assert analyze(store, cfg.ab_campaign).decision is Decision.B_BETTER


# --- serialisation + CLI -----------------------------------------------------


def test_to_dict_and_to_html(tmp_path):
    store = CampaignStore(tmp_path / "s.jsonl")
    cfg = _config(30)
    record_run(store, cfg, now=FIXED)
    result = analyze(store, cfg.ab_campaign)
    d = result.to_dict()
    assert d["decision"] == "b_better"
    assert set(d["arms"]) == {"hi", "lo"}
    json.dumps(d)
    html = result.to_html()
    assert "<!DOCTYPE html>" in html and "b_better" in html
    assert "http://" not in html and "https://" not in html


def test_cli_record_then_analyze(tmp_path):
    import yaml

    cfg = _config(30)
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    store = tmp_path / "s.jsonl"
    json_out = tmp_path / "r.json"

    rc = cli_main(["campaign", "--config", str(cfg_path), "--store", str(store), "--offline"])
    assert rc == 0
    rc = cli_main(
        [
            "campaign",
            "--config",
            str(cfg_path),
            "--store",
            str(store),
            "--mode",
            "analyze",
            "--json",
            str(json_out),
        ]
    )
    assert rc == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["decision"] == "b_better"


def test_cli_campaign_without_block_errors(tmp_path):
    import yaml

    cfg = EvalConfig(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {"items": _items(1)}},
        target={"type": "echo", "params": {}},
    )
    cfg_path = tmp_path / "p.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    rc = cli_main(["campaign", "--config", str(cfg_path), "--store", str(tmp_path / "s.jsonl")])
    assert rc == 2
