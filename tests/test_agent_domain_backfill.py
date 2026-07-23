"""Tests for scripts/migrations/agent_domain_backfill.py (F-044) — pure backfill logic."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import agent_confidence as ac  # scripts/ is on sys.path via tests/conftest.py
import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(str(_ROOT), "scripts", "migrations"))

import agent_domain_backfill as adb  # noqa: E402
from agent_core.outcome_store import LabelSource, OutcomeRecord, OutcomeStore  # noqa: E402

_TS = "2026-07-20T12:00:00+00:00"
_PROXY = str(_ROOT / "config" / "agent-confidence.yaml")


def _rec(cid, domain, conf, source=None, label=None):
    return OutcomeRecord(
        cid, domain, conf, _TS, label=label, label_source=(source.value if source else None), labeled_at=None
    )


# --- pure helpers -----------------------------------------------------------
def test_strip_human_namespace():
    assert adb.strip_human_namespace("human/agent-core") == "agent-core"
    assert adb.strip_human_namespace("agent-core") == "agent-core"


def test_parse_shas_file():
    text = "# header\n\nabc123 claude-code\n  # comment\nghi789 devin\n"
    parsed = adb.parse_shas_file(text)
    assert parsed == {"abc123": "claude-code", "ghi789": "devin"}


def test_parse_shas_file_requires_explicit_version():
    # A bare SHA (no agent_version) is a malformed line and must raise, not silently default.
    with pytest.raises(ValueError, match="agent_version"):
        adb.parse_shas_file("abc123\n")


def test_render_diff_empty():
    assert "no changes" in adb.render_diff([])


# --- plan_backfill ----------------------------------------------------------
def test_plan_backfill_redomains_all_records_of_target():
    records = [
        _rec("c1", "human/agent-core", 0.0),
        _rec("c1", "human/agent-core", 0.0, LabelSource.TIMEOUT_CLEAN, True),
        _rec("c2", "human/eval-harness", 0.0),  # untargeted
    ]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    new, diffs = adb.plan_backfill(records, targets)
    c1 = [r for r in new if r.change_id == "c1"]
    assert all(r.domain == "agent-core" and r.raw_confidence == 0.8 and r.agent_version == "claude-code" for r in c1)
    # the passive label is preserved, only the domain/confidence/version change
    assert any(r.label_source == LabelSource.TIMEOUT_CLEAN.value for r in c1)
    # untargeted record untouched
    assert next(r for r in new if r.change_id == "c2").domain == "human/eval-harness"
    assert len(diffs) == 2


def test_plan_backfill_is_idempotent():
    records = [_rec("c1", "human/agent-core", 0.0)]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    once, _ = adb.plan_backfill(records, targets)
    twice, diffs = adb.plan_backfill(once, targets)
    assert twice == once
    assert diffs == []  # nothing left to change


def test_plan_backfill_refuses_human_audit():
    records = [_rec("c1", "human/agent-core", 0.0, LabelSource.HUMAN_AUDIT, True)]
    targets = {"c1": adb.BackfillTarget("claude-code", 0.8)}
    with pytest.raises(ValueError, match="HUMAN_AUDIT"):
        adb.plan_backfill(records, targets)


# --- CLI (git-free via monkeypatched confidence) ----------------------------
def _seed_store(tmp_path, records):
    store = OutcomeStore(tmp_path / "s.jsonl")
    for r in records:
        store.append(r)
    return store


def _shas_file(tmp_path, ids):
    p = tmp_path / "shas.txt"
    p.write_text("".join(f"{i} claude-code\n" for i in ids), encoding="utf-8")
    return str(p)


def test_main_dry_run_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(adb, "compute_confidence_for", lambda cid, repo_dir, proxy: 0.7)
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0), _rec("c2", "human/docs", 0.0)])
    before = store.path.read_text(encoding="utf-8")
    rc = adb.main(["--store", str(store.path), "--shas-file", _shas_file(tmp_path, ["c1"]), "--proxy-config", _PROXY])
    assert rc == 0
    assert store.path.read_text(encoding="utf-8") == before  # untouched
    assert not (tmp_path / "s.jsonl.pre-backfill.bak").exists()
    assert "agent-core" in capsys.readouterr().out


def test_main_apply_rewrites_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setattr(adb, "compute_confidence_for", lambda cid, repo_dir, proxy: 0.7)
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0), _rec("c2", "human/docs", 0.0)])
    rc = adb.main(
        ["--store", str(store.path), "--shas-file", _shas_file(tmp_path, ["c1"]), "--proxy-config", _PROXY, "--apply"]
    )
    assert rc == 0
    assert (tmp_path / "s.jsonl.pre-backfill.bak").exists()
    resolved = {r.change_id: r for r in OutcomeStore(store.path).all()}
    assert resolved["c1"].domain == "agent-core" and resolved["c1"].raw_confidence == 0.7
    assert resolved["c1"].agent_version == "claude-code"
    assert resolved["c2"].domain == "human/docs"  # untargeted, unchanged


# --- git-facing functions over a real temporary repo ------------------------
def _git_repo_with_change(path: Path) -> str:
    """Init a repo with two commits; return the HEAD sha (the 'change' to score)."""
    ident = ["-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(path), *ident, *args], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, capture_output=True)
    (path / "a.py").write_text("x = 1\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    (path / "b.py").write_text("y = 2\n" * 30, encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "change")
    out = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def test_compute_confidence_for_over_real_git(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = _git_repo_with_change(repo)
    conf = adb.compute_confidence_for(sha, str(repo), ac.ProxyConfig.load(_PROXY))
    assert 0.0 < conf < 1.0  # a real diff yields a valid proxy confidence


def test_build_targets_over_real_git(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sha = _git_repo_with_change(repo)
    targets = adb.build_targets({sha: "claude-code"}, str(repo), ac.ProxyConfig.load(_PROXY))
    assert set(targets) == {sha}
    assert targets[sha].agent_version == "claude-code"
    assert 0.0 < targets[sha].confidence < 1.0


def test_git_helper_raises_on_bad_ref(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo_with_change(repo)
    with pytest.raises(RuntimeError, match="git"):
        adb._git(["rev-parse", "--verify", "does-not-exist"], str(repo))


def test_git_helper_error_names_the_repo(tmp_path):
    # The RuntimeError must name repo_dir so a wrong --repo-dir / shallow clone is diagnosable.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo_with_change(repo)
    with pytest.raises(RuntimeError, match=str(repo)):
        adb._git(["rev-parse", "--verify", "does-not-exist"], str(repo))


def test_compute_confidence_for_handles_binary_files(tmp_path):
    """`git diff --numstat` emits '-\\t-' for binary files; those rows must contribute 0 lines,
    not crash the int coercion. A backfilled agent change may touch an image/binary."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ident = ["-c", "user.email=t@e", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *ident, *args], check=True, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    # A binary blob (all byte values) makes numstat show '-\t-'; also change a text file.
    (repo / "img.bin").write_bytes(bytes(range(256)) * 8)
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "binary + text change")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    # Exercises the `if n.isdigit()` False arc (binary '-' columns) without crashing.
    conf = adb.compute_confidence_for(sha, str(repo), ac.ProxyConfig.load(_PROXY))
    assert 0.0 < conf < 1.0


def test_main_warns_on_missing_change_id(tmp_path, caplog, monkeypatch):
    # A hand-verified change_id absent from the store must be skipped with a visible warning —
    # the only signal that it silently won't be backfilled.
    monkeypatch.setattr(adb, "compute_confidence_for", lambda cid, repo_dir, proxy: 0.7)
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0)])
    with caplog.at_level("WARNING"):
        rc = adb.main(
            ["--store", str(store.path), "--shas-file", _shas_file(tmp_path, ["c1", "c9"]), "--proxy-config", _PROXY]
        )
    assert rc == adb.EXIT_OK
    assert "not in the store" in caplog.text and "c9" in caplog.text


def test_main_bad_proxy_config_is_clean_exit(tmp_path):
    # An unreadable proxy config must surface as a clean exit 2, not a traceback (matches siblings).
    store = _seed_store(tmp_path, [_rec("c1", "human/agent-core", 0.0)])
    rc = adb.main(
        [
            "--store",
            str(store.path),
            "--shas-file",
            _shas_file(tmp_path, ["c1"]),
            "--proxy-config",
            str(tmp_path / "does-not-exist.yaml"),
        ]
    )
    assert rc == adb.EXIT_CONFIG
