"""Tests for the model-bench skill runner (``scripts/run.py``).

The runner is a thin forwarder over the eval-harness ``compare``/``campaign`` CLI.
These tests drive it directly over the bundled ``echo``-target fixtures (offline,
deterministic) and check the usage-error and import-error branches with no network.
``langfuse-eval-harness`` must be importable — model-bench wraps it by definition.
"""

from __future__ import annotations

import json
import os
import sys

import pytest
import run

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPARE_CFG = os.path.join(SKILL, "evals", "fixtures", "compare.yaml")
CAMPAIGN_CFG = os.path.join(SKILL, "evals", "fixtures", "campaign.yaml")

pytest.importorskip("eval_harness")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- usage / errors
def test_no_args_prints_usage_and_exits_two(capsys):
    assert run.main([]) == 2
    assert "usage: run.py" in capsys.readouterr().err


def test_unknown_subcommand_exits_two():
    assert run.main(["frobnicate"]) == 2


def test_missing_harness_returns_one(monkeypatch):
    # Simulate the harness not being installed: a None entry makes the import fail.
    monkeypatch.setitem(sys.modules, "eval_harness.cli", None)
    assert run.main(["compare", "--config", COMPARE_CFG, "--offline"]) == 1


# ----------------------------------------------------------------------- compare
def test_compare_ranks_models(capsys):
    assert run.main(["compare", "--config", COMPARE_CFG, "--offline"]) == 0
    assert "good-model > bad-model" in capsys.readouterr().out


def test_compare_writes_json_report(tmp_path):
    out = str(tmp_path / "cmp.json")
    assert run.main(["compare", "--config", COMPARE_CFG, "--offline", "--json", out]) == 0
    assert set(_read_json(out)["runs"]) == {"good-model", "bad-model"}


def test_compare_missing_block_exits_two():
    # The plain comparison fixture has the block; point at the campaign fixture
    # (no 'comparison' block) to hit the harness's "nothing to compare" guard.
    assert run.main(["compare", "--config", CAMPAIGN_CFG, "--offline"]) == 2


# ---------------------------------------------------------------------- campaign
def test_campaign_record_then_analyze(tmp_path, capsys):
    store = str(tmp_path / "store.jsonl")
    assert run.main(["campaign", "--config", CAMPAIGN_CFG, "--store", store, "--mode", "record", "--offline"]) == 0
    rec_out = capsys.readouterr().out
    assert "candidate: 1/1" in rec_out

    out = str(tmp_path / "analysis.json")
    assert (
        run.main(
            ["campaign", "--config", CAMPAIGN_CFG, "--store", store, "--mode", "analyze", "--offline", "--json", out]
        )
        == 0
    )
    assert "decision:" in capsys.readouterr().out
    assert "decision" in _read_json(out)


def test_argv_defaults_to_sys_argv(monkeypatch, capsys):
    # main(None) reads sys.argv[1:].
    monkeypatch.setattr(sys, "argv", ["run.py"])
    assert run.main() == 2
    assert "usage: run.py" in capsys.readouterr().err
