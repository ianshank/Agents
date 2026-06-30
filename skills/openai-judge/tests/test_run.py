"""Offline tests for the openai-judge skill runner (``scripts/run.py``).

Deterministic and offline: the mock path writes a canned verdict, and the live
path is exercised with a fake ``eval_harness.judges`` module injected into
``sys.modules`` (no real SDK, no network). Together they cover the runner's
success, file-error, import-error, and evaluation-error branches.
"""

from __future__ import annotations

import json
import sys
import types

import pytest
import run


def _write(path, text="x"):
    path.write_text(text, encoding="utf-8")
    return str(path)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _args(tmp_path, *extra):
    prompt = _write(tmp_path / "prompt.txt", "is this good?")
    rubric = _write(tmp_path / "rubric.txt", "score 0..1")
    out = str(tmp_path / "nested" / "out.json")  # nested dir must be created by the runner
    return ["run.py", "--prompt", prompt, "--rubric", rubric, "--out", out, *extra], out


# ------------------------------------------------------------------------ mock
def test_mock_mode_writes_verdict_and_exits_zero(tmp_path, monkeypatch, capsys):
    argv, out = _args(tmp_path, "--mock")
    monkeypatch.setattr(sys, "argv", argv)

    assert run.main() == 0
    verdict = _read_json(out)
    assert verdict["status"] == "ok"
    assert verdict["score"] == 1.0
    assert "Mock run succeeded" in capsys.readouterr().out


# ------------------------------------------------------------------ file error
def test_missing_input_file_returns_one(tmp_path, monkeypatch):
    argv = [
        "run.py",
        "--prompt",
        str(tmp_path / "nope.txt"),
        "--rubric",
        str(tmp_path / "nope2.txt"),
        "--out",
        str(tmp_path / "o.json"),
        "--mock",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    assert run.main() == 1


# ------------------------------------------------------------------- live mode
def _inject_fake_judge(monkeypatch, *, score=0.9, raises=False):
    fake = types.ModuleType("eval_harness.judges")

    class FakeJudge:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def evaluate(self, prompt):
            if raises:
                raise RuntimeError("model exploded")
            return types.SimpleNamespace(score=score, reasoning="because", raw={"p": prompt})

    fake.OpenAIJudge = FakeJudge  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "eval_harness.judges", fake)


def test_live_mode_success_writes_verdict(tmp_path, monkeypatch):
    _inject_fake_judge(monkeypatch, score=0.75)
    argv, out = _args(tmp_path)  # no --mock
    monkeypatch.setattr(sys, "argv", argv)

    assert run.main() == 0
    verdict = _read_json(out)
    assert verdict["score"] == 0.75
    assert verdict["reasoning"] == "because"


def test_live_mode_import_error_returns_one(tmp_path, monkeypatch):
    # A None entry makes `from eval_harness.judges import OpenAIJudge` raise ImportError.
    monkeypatch.setitem(sys.modules, "eval_harness.judges", None)
    argv, _ = _args(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    assert run.main() == 1


def test_live_mode_evaluation_error_returns_one(tmp_path, monkeypatch):
    _inject_fake_judge(monkeypatch, raises=True)
    argv, _ = _args(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    assert run.main() == 1


# --------------------------------------------------------------------- argparse
def test_missing_required_args_exit_nonzero(monkeypatch):
    # run.py declares --prompt/--rubric/--out as required → argparse exits.
    monkeypatch.setattr(sys, "argv", ["run.py", "--mock"])
    with pytest.raises(SystemExit):
        run.main()
