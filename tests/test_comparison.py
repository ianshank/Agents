"""Tests for F-024 — multi-model comparison."""

from __future__ import annotations

import json
from typing import Any

import pytest

from eval_harness.cli import main as cli_main
from eval_harness.comparison import ComparisonResult, compare_metric, run_comparison
from eval_harness.config.models import ComparisonConfig, EvalConfig
from eval_harness.version import SCHEMA_VERSION

# Two echo models over one item: "good" echoes the field matching `expected`,
# "bad" echoes the other -> exact_match is 1.0 vs 0.0, deterministically.
_ITEMS = [{"id": "1", "inputs": {"a": "x", "b": "y"}, "expected": "x"}]


def _config(**comparison: Any) -> EvalConfig:
    return EvalConfig.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "run": {"name": "cmp"},
            "dataset": {"type": "inline", "params": {"items": _ITEMS}},
            "target": {"type": "echo", "params": {}},  # overridden per-model
            "scorers": [{"type": "exact_match", "params": {}}],
            "comparison": {
                "models": [
                    {"name": "good", "target": {"type": "echo", "params": {"output_key": "a"}}},
                    {"name": "bad", "target": {"type": "echo", "params": {"output_key": "b"}}},
                ],
                **comparison,
            },
        }
    )


# --- ComparisonConfig validation --------------------------------------------


def test_requires_at_least_two_models():
    with pytest.raises(ValueError):
        ComparisonConfig(models=[{"name": "a", "target": {"type": "echo"}}])


def test_unique_model_names():
    with pytest.raises(ValueError, match="unique"):
        ComparisonConfig(
            models=[
                {"name": "a", "target": {"type": "echo"}},
                {"name": "a", "target": {"type": "echo"}},
            ]
        )


def test_baseline_must_be_a_model():
    with pytest.raises(ValueError, match="baseline"):
        ComparisonConfig(
            models=[
                {"name": "a", "target": {"type": "echo"}},
                {"name": "b", "target": {"type": "echo"}},
            ],
            baseline="zzz",
        )


def test_rank_metric_validated():
    with pytest.raises(ValueError, match="rank_metric"):
        ComparisonConfig(
            models=[
                {"name": "a", "target": {"type": "echo"}},
                {"name": "b", "target": {"type": "echo"}},
            ],
            rank_metric="bogus",
        )


# --- compare_metric primitive (shared with F-025) ---------------------------


def test_run_comparison_ranks_and_deltas():
    result = run_comparison(_config(baseline="good"))
    assert isinstance(result, ComparisonResult)
    assert result.overall_ranking == ["good", "bad"]
    [cmp] = result.comparisons  # one score: exact_match
    assert cmp.values == {"good": 1.0, "bad": 0.0}
    assert cmp.deltas == {"good": 0.0, "bad": -1.0}  # vs good baseline


def test_run_comparison_without_baseline_has_none_deltas():
    result = run_comparison(_config())
    [cmp] = result.comparisons
    assert cmp.deltas == {"good": None, "bad": None}
    assert cmp.ranking == ["good", "bad"]


def test_compare_metric_ranks_none_last():
    # Build a synthetic case where one model lacks the score.
    result = run_comparison(_config())
    runs = result.runs
    cmp = compare_metric(runs, score="exact_match", metric="mean", baseline=None)
    assert cmp.ranking == ["good", "bad"]
    missing = compare_metric(runs, score="not_a_score", metric="mean")
    assert all(v is None for v in missing.values.values())


def test_run_comparison_requires_comparison_config():
    cfg = EvalConfig(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {"items": _ITEMS}},
        target={"type": "echo", "params": {}},
    )
    with pytest.raises(ValueError, match="comparison config"):
        run_comparison(cfg)


# --- serialisation -----------------------------------------------------------


def test_to_dict_round_trip():
    d = run_comparison(_config(baseline="good")).to_dict()
    assert d["overall_ranking"] == ["good", "bad"]
    assert set(d["runs"]) == {"good", "bad"}
    assert d["comparisons"][0]["values"] == {"good": 1.0, "bad": 0.0}
    # JSON-serialisable
    json.dumps(d)


def test_to_html_is_deterministic_and_escaped():
    result = run_comparison(_config(baseline="good"))
    html_a = result.to_html()
    html_b = result.to_html()
    assert html_a == html_b  # deterministic
    assert "<!DOCTYPE html>" in html_a
    assert "exact_match" in html_a
    # no external resources
    assert "http://" not in html_a and "https://" not in html_a


# --- CLI ---------------------------------------------------------------------


def test_cli_compare_writes_reports(tmp_path):
    import yaml

    cfg = _config(baseline="good")
    cfg_path = tmp_path / "cmp.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    html_out = tmp_path / "r.html"
    json_out = tmp_path / "r.json"
    rc = cli_main(
        [
            "compare",
            "--config",
            str(cfg_path),
            "--offline",
            "--html",
            str(html_out),
            "--json",
            str(json_out),
        ]
    )
    assert rc == 0
    assert "<!DOCTYPE html>" in html_out.read_text(encoding="utf-8")
    loaded = json.loads(json_out.read_text(encoding="utf-8"))
    assert loaded["overall_ranking"] == ["good", "bad"]


def test_cli_compare_without_comparison_block_errors(tmp_path):
    import yaml

    cfg = EvalConfig(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {"items": _ITEMS}},
        target={"type": "echo", "params": {}},
    )
    cfg_path = tmp_path / "plain.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    rc = cli_main(["compare", "--config", str(cfg_path), "--offline"])
    assert rc == 2
