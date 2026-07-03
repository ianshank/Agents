"""End-to-end tests: drive the runner CLI over the bundled fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(SKILL, "scripts", "run_eval_corpus_forge.py")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _run(args):
    return subprocess.run(
        [sys.executable, RUNNER, *args],
        cwd=SKILL,
        capture_output=True,
        text=True,
    )


def test_full_dataset_end_to_end(tmp_path):
    out = str(tmp_path / "full")
    r = _run(["--in", "evals/fixtures/full-dataset", "--out", out])
    assert r.returncode == 0, r.stderr
    m = _read_json(os.path.join(out, "manifest.json"))
    assert m["mode"] == "full_dataset"
    assert m["validation"]["status"] == "passed"
    assert m["counts"]["canonical_scenarios"] == 2
    # all four views populated for this fixture
    for key in (
        "retrieval_eval_records",
        "tool_invocation_eval_records",
        "response_eval_records",
        "end_to_end_eval_records",
    ):
        assert m["counts"][key] >= 1


def test_determinism_across_runs(tmp_path):
    out1, out2 = str(tmp_path / "a"), str(tmp_path / "b")
    assert _run(["--in", "evals/fixtures/full-dataset", "--out", out1]).returncode == 0
    assert _run(["--in", "evals/fixtures/full-dataset", "--out", out2]).returncode == 0
    s1 = _read_text(os.path.join(out1, "canonical", "scenarios.jsonl"))
    s2 = _read_text(os.path.join(out2, "canonical", "scenarios.jsonl"))
    assert s1 == s2


def test_bootstrap_marks_views_not_applicable(tmp_path):
    out = str(tmp_path / "boot")
    r = _run(["--in", "evals/fixtures/bootstrap", "--out", out])
    assert r.returncode == 0, r.stderr
    m = _read_json(os.path.join(out, "manifest.json"))
    assert m["mode"] == "bootstrap"
    va = m["view_applicability"]
    assert va["tool_invocation_eval"]["applicable"] is False
    assert va["tool_invocation_eval"]["reason"]
    # empty files, not placeholders
    assert os.path.getsize(os.path.join(out, "views", "tool_invocation_eval.jsonl")) == 0


def test_no_prompts_stops_without_package(tmp_path):
    out = str(tmp_path / "nop")
    r = _run(["--in", "evals/fixtures/no-prompts", "--out", out])
    assert r.returncode == 1
    assert "no prompts or scenarios" in (r.stdout + r.stderr)
    assert not os.path.exists(out)
