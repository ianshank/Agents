"""Tests for scripts/check_branch_protection.py (advisory ADR 0037 checker)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import check_branch_protection as chk
import pytest
from required_check_names import candidate_required_contexts


def test_real_repo_derives_a_non_empty_expected_set() -> None:
    names = candidate_required_contexts()
    assert names
    report = chk.build_report(repo_root=Path(__file__).resolve().parent.parent, probe=False)
    assert report.expected == names
    assert report.ok is True  # no probe => nothing to disagree with
    assert report.live_contexts is None


def test_parse_owner_repo_from_env_and_arg() -> None:
    cfg = chk.BranchProtectionConfig()
    assert chk.parse_owner_repo(None, cfg, {}) is None
    assert chk.parse_owner_repo(None, cfg, {cfg.repository_env_var: "acme/widgets"}) == (
        "acme",
        "widgets",
    )
    assert chk.parse_owner_repo("acme/widgets", cfg, {}) == ("acme", "widgets")
    assert chk.parse_owner_repo("nope", cfg, {}) is None


def test_contexts_from_protection_payload_unions_both_shapes() -> None:
    payload = {
        "required_status_checks": {
            "contexts": ["a"],
            "checks": [{"context": "b", "app_id": 1}, {"context": "a"}],
        }
    }
    assert chk.contexts_from_protection_payload(payload) == ("a", "b")


def test_probe_404_is_unprotected_not_an_error() -> None:
    def runner(args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="gh: Not Found (HTTP 404)")

    protected, live, err = chk.probe_protection("acme", "widgets", runner=runner)
    assert protected is False and live == () and err is None


def test_strict_fails_when_unprotected(capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parent.parent

    def runner(args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Not Found")

    report = chk.build_report(
        repo_root=root,
        probe=True,
        owner_repo="acme/widgets",
        runner=runner,
    )
    assert report.protected is False
    assert report.missing == report.expected
    assert report.ok is False
    assert chk.main(["--repo-root", str(root)]) == 0  # advisory
    capsys.readouterr()
    # --strict without --probe still ok (nothing missing from a skipped probe)
    assert chk.main(["--repo-root", str(root), "--strict"]) == 0


def test_strict_probe_without_repository_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = Path(__file__).resolve().parent.parent
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    rc = chk.main(["--repo-root", str(root), "--probe", "--strict"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "probe_error=" in out


def test_strict_probe_missing_check_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parent.parent
    expected = candidate_required_contexts(repo=root)

    monkeypatch.setattr(
        chk,
        "probe_protection",
        lambda *a, **k: (True, tuple(expected[1:]), None),
    )
    rc = chk.main(["--repo-root", str(root), "--probe", "--strict", "--repository", "acme/widgets"])
    assert rc == 1
