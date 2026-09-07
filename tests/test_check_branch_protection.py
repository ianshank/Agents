"""Tests for scripts/check_branch_protection.py (advisory ADR 0037 checker)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import check_branch_protection as chk
import pytest
from required_check_names import (
    CheckNameError,
    candidate_required_contexts,
    enablement_required_contexts,
    extra_required_contexts,
    load_workflow,
    rendered_job_names,
)


def test_real_repo_derives_a_non_empty_expected_set() -> None:
    root = Path(__file__).resolve().parent.parent
    stubs = candidate_required_contexts(repo=root)
    extras = extra_required_contexts(repo=root)
    names = enablement_required_contexts(repo=root)
    assert stubs and extras
    assert names == tuple(sorted({*stubs, *extras}))
    report = chk.build_report(repo_root=root, probe=False)
    assert report.expected == names
    assert report.ok is True  # no probe => nothing to disagree with
    assert report.live_contexts is None
    extra_path = root / chk.BranchProtectionConfig().extra_required_workflows[0]
    assert extras == tuple(sorted(rendered_job_names(load_workflow(extra_path))))


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
    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="gh: Not Found (HTTP 404)")

    protected, live, err = chk.probe_protection("acme", "widgets", runner=runner)
    assert protected is False and live == () and err is None


def test_strict_fails_when_unprotected(capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parent.parent

    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
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
    expected = enablement_required_contexts(repo=root)

    monkeypatch.setattr(
        chk,
        "probe_protection",
        lambda *a, **k: (True, tuple(expected[1:]), None),
    )
    rc = chk.main(["--repo-root", str(root), "--probe", "--strict", "--repository", "acme/widgets"])
    assert rc == 1


def test_extra_required_contexts_missing_file_is_loud(tmp_path: Path) -> None:
    with pytest.raises(CheckNameError, match="missing"):
        extra_required_contexts(repo=tmp_path, extra_workflows=("nope.yml",))


def test_extra_required_contexts_empty_override_is_empty(tmp_path: Path) -> None:
    assert extra_required_contexts(repo=tmp_path, extra_workflows=()) == ()


def test_protection_payload_uses_config_defaults_and_sorted_contexts() -> None:
    import branch_protection_rule as rule

    cfg = rule.ProtectionRuleConfig()
    payload = rule.build_protection_payload(("z-check", "a-check"), cfg)
    checks = payload["required_status_checks"]
    assert checks["contexts"] == ["a-check", "z-check"]
    assert checks["checks"] == [{"context": "a-check"}, {"context": "z-check"}]
    assert checks["strict"] is cfg.require_up_to_date
    assert payload["enforce_admins"] is cfg.enforce_admins
    reviews = payload["required_pull_request_reviews"]
    assert reviews["required_approving_review_count"] == cfg.required_approving_review_count
    assert reviews["require_code_owner_reviews"] is cfg.require_code_owner_reviews
    assert payload["allow_force_pushes"] is cfg.allow_force_pushes
    assert payload["allow_deletions"] is cfg.allow_deletions
    assert payload["restrictions"] is None


def test_protection_payload_rejects_an_empty_set() -> None:
    import branch_protection_rule as rule

    with pytest.raises(ValueError, match="empty"):
        rule.build_protection_payload((), rule.ProtectionRuleConfig())


def test_apply_protection_put_uses_stdin_json() -> None:
    import branch_protection_rule as rule

    captured: dict[str, object] = {}
    payload = rule.build_protection_payload(("ctx",), rule.ProtectionRuleConfig())

    def runner(args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        captured["args"] = list(args)
        captured["stdin"] = stdin
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    ok, err = rule.apply_protection_rule("acme", "widgets", payload, runner=runner)
    assert ok is True and err is None
    args = captured["args"]
    assert isinstance(args, list)
    assert args[0] == "api" and "--method" in args and "PUT" in args
    assert args[-2:] == ["--input", "-"]
    assert captured["stdin"] == rule.payload_json(payload)


def test_apply_protection_403_is_not_enabled() -> None:
    import branch_protection_rule as rule

    payload = rule.build_protection_payload(("ctx",), rule.ProtectionRuleConfig())

    def runner(args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args, 1, stdout="", stderr="gh: Resource not accessible by integration (HTTP 403)"
        )

    ok, err = rule.apply_protection_rule("acme", "widgets", payload, runner=runner)
    assert ok is False
    assert err is not None and "403" in err


def test_apply_oserror_is_not_enabled() -> None:
    import branch_protection_rule as rule

    payload = rule.build_protection_payload(("ctx",), rule.ProtectionRuleConfig())

    def runner(args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        raise OSError("gh missing")

    ok, err = rule.apply_protection_rule("acme", "widgets", payload, runner=runner)
    assert ok is False and err is not None
    assert "gh missing" in err


def test_emit_payload_is_valid_json_of_the_enablement_set(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    import branch_protection_rule as rule

    root = Path(__file__).resolve().parent.parent
    rc = chk.main(["--repo-root", str(root), "--emit-payload"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    expected = enablement_required_contexts(repo=root)
    assert payload["required_status_checks"]["contexts"] == list(expected)
    assert payload["enforce_admins"] is rule.ProtectionRuleConfig().enforce_admins


def test_apply_without_repository_exits_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parent.parent
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    rc = chk.main(["--repo-root", str(root), "--apply"])
    assert rc == 2
    capsys.readouterr()


def test_apply_refused_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(
        chk,
        "apply_protection_rule",
        lambda *a, **k: (False, "gh: Resource not accessible by integration (HTTP 403)"),
    )
    rc = chk.main(["--repo-root", str(root), "--apply", "--repository", "acme/widgets"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "apply_error=" in err


def test_enforce_admins_flag_flips_payload(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    root = Path(__file__).resolve().parent.parent
    rc = chk.main(["--repo-root", str(root), "--emit-payload", "--enforce-admins"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enforce_admins"] is True


def test_extra_workflow_cli_replaces_the_config_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    root = Path(__file__).resolve().parent.parent
    captured: dict[str, object] = {}

    def fake_enablement(
        *,
        repo: Path,
        stub_workflow: str,
        extra_workflows: tuple[str, ...] | None,
    ) -> tuple[str, ...]:
        captured["extra"] = extra_workflows
        return ("only-check",)

    monkeypatch.setattr(chk, "enablement_required_contexts", fake_enablement)
    rc = chk.main(
        [
            "--repo-root",
            str(root),
            "--emit-payload",
            "--extra-workflow",
            "docs/not-a-default.yml",
        ]
    )
    assert rc == 0
    assert captured["extra"] == ("docs/not-a-default.yml",)
    payload = json.loads(capsys.readouterr().out)
    assert payload["required_status_checks"]["contexts"] == ["only-check"]


def test_apply_accepted_prints_applied(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(chk, "apply_protection_rule", lambda *a, **k: (True, None))
    rc = chk.main(["--repo-root", str(root), "--apply", "--repository", "acme/widgets"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "applied=true" in err
    assert "required_checks=" in err


def test_apply_timeout_is_not_enabled() -> None:
    import branch_protection_rule as rule

    payload = rule.build_protection_payload(("ctx",), rule.ProtectionRuleConfig())

    def runner(args: Sequence[str], stdin: str) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=1)

    ok, err = rule.apply_protection_rule("acme", "widgets", payload, runner=runner)
    assert ok is False and err is not None
    assert "timed out" in err.lower() or "TimeoutExpired" in err


def test_protection_payload_drops_blank_context_names() -> None:
    import branch_protection_rule as rule

    payload = rule.build_protection_payload(("keep", "  ", ""), rule.ProtectionRuleConfig())
    assert payload["required_status_checks"]["contexts"] == ["keep"]


def test_apply_default_runner_invokes_configured_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    import branch_protection_rule as rule

    calls: list[list[str]] = []

    def fake_run(args: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")

    monkeypatch.setattr(rule.subprocess, "run", fake_run)
    payload = rule.build_protection_payload(("ctx",), rule.ProtectionRuleConfig())
    cfg = rule.ProtectionApplyConfig()
    ok, err = rule.apply_protection_rule("acme", "widgets", payload, cfg=cfg)
    assert ok is True and err is None
    assert calls and calls[0][0] == cfg.gh_command
    assert "--method" in calls[0] and "PUT" in calls[0]


def test_probe_default_runner_treats_404_as_unprotected(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = chk.BranchProtectionConfig()

    def fake_run(args: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="gh: Not Found (HTTP 404)")

    monkeypatch.setattr(chk.subprocess, "run", fake_run)
    protected, live, err = chk.probe_protection("acme", "widgets", cfg)
    assert protected is False and live == () and err is None


def test_probe_bad_json_is_an_error() -> None:
    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="not-json", stderr="")

    protected, live, err = chk.probe_protection("acme", "widgets", runner=runner)
    assert protected is None and live is None
    assert err is not None and "not JSON" in err


def test_probe_non_object_payload_is_an_error() -> None:
    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    protected, live, err = chk.probe_protection("acme", "widgets", runner=runner)
    assert protected is None and live is None
    assert err is not None and "not an object" in err


def test_probe_oserror_is_an_error() -> None:
    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise OSError("gh missing")

    protected, live, err = chk.probe_protection("acme", "widgets", runner=runner)
    assert protected is None and live is None
    assert err is not None and "gh missing" in err
