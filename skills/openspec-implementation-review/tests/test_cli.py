"""End-to-end tests of the CLI entrypoint (implreview.cli.main), in-process.

These call ``main()`` directly with an argv list rather than spawning a subprocess, matching
how ``evals/evals.json`` exercises the *real* ``python scripts/run.py`` process separately —
this file's job is fast, precise coverage of every branch; the evals prove the real CLI
process wires up the same way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from implreview.cli import main

_GOOD_BODY = """\
## Verdict

**APPROVE.** Looks fine.

---

## Pass 1 -- mechanical fact-check (2026-08-17)

Confirmed everything.

## Pass 2 -- adversarial (2026-08-17)

Tried to break it, could not.

## Residual risk

None.

## Overall verdict

**APPROVE.**
"""


def _make_change(repo_root: Path, change_id: str, *, tasks_text: str = "- [x] done\n") -> Path:
    change_dir = repo_root / "openspec" / "changes" / change_id
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text(f"# Change: {change_id}\n", encoding="utf-8")
    (change_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
    return change_dir


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "openspec" / "changes").mkdir(parents=True)
    return tmp_path


# --- locate ----------------------------------------------------------------------------------


def test_locate_happy_path(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_change(repo_root, "demo-change")
    rc = main(["locate", "--repo", str(repo_root), "--change", "demo-change"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "demo-change" in out
    assert "(complete)" in out


def test_locate_bogus_change_id_is_a_clean_nonzero_exit(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_change(repo_root, "real-change")
    rc = main(["locate", "--repo", str(repo_root), "--change", "totally-bogus-id"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "no such change" in captured.err
    assert "totally-bogus-id" in captured.err


def test_locate_incomplete_tasks_is_nonzero_by_default(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_change(repo_root, "wip-change", tasks_text="- [x] one\n- [ ] two\n")
    rc = main(["locate", "--repo", str(repo_root), "--change", "wip-change"])
    assert rc == 1
    assert "allow-incomplete" in capsys.readouterr().err


def test_locate_allow_incomplete_overrides(repo_root: Path) -> None:
    _make_change(repo_root, "wip-change", tasks_text="- [x] one\n- [ ] two\n")
    rc = main(["locate", "--repo", str(repo_root), "--change", "wip-change", "--allow-incomplete"])
    assert rc == 0


def test_locate_json_output_is_parseable(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_change(repo_root, "demo-change")
    rc = main(["locate", "--repo", str(repo_root), "--change", "demo-change", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["change_id"] == "demo-change"
    # dataclasses.asdict() serializes fields only, not @property values (`complete` is
    # computed) -- so the JSON contract is checked/total, matched here explicitly.
    assert payload["tasks_status"]["checked"] == payload["tasks_status"]["total"] == 1


def test_locate_reports_missing_tasks_md_in_text_mode(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    change_dir = repo_root / "openspec" / "changes" / "no-tasks-yet"
    change_dir.mkdir(parents=True)
    (change_dir / "proposal.md").write_text("# Change: no-tasks-yet\n", encoding="utf-8")
    rc = main(["locate", "--repo", str(repo_root), "--change", "no-tasks-yet"])
    assert rc == 0  # no tasks.md at all is not the same failure as an incomplete one
    assert "tasks.md: not found" in capsys.readouterr().out


# --- detect ------------------------------------------------------------------------------------


def test_detect_always_exits_zero_and_reports_degraded_without_plugin_files(
    repo_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    rc = main(["detect", "--repo", str(repo_root), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["charters_present"] is False
    assert payload["recommended_path"] == "degraded"


def test_detect_text_mode_prints_every_field(
    repo_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    rc = main(["detect", "--repo", str(repo_root)])
    out = capsys.readouterr().out
    assert rc == 0
    for field in (
        "charters_present:",
        "plugin_manifest_present:",
        "claude_plugin_root:",
        "env_signals_plugin_loaded:",
        "recommended_path:",
        "confidence:",
        "reason:",
    ):
        assert field in out


# --- plan --------------------------------------------------------------------------------------


def test_plan_bogus_change_is_nonzero(repo_root: Path) -> None:
    rc = main(["plan", "--repo", str(repo_root), "--change", "nope"])
    assert rc == 2


def test_plan_degraded_path_prints_general_purpose_dispatch(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_change(repo_root, "demo-change")
    rc = main(
        [
            "plan",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--force-path",
            "degraded",
            "--tree-sha",
            "abc123",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "general-purpose" in out
    assert "abc123" in out


def test_plan_without_tree_sha_falls_back_to_the_unknown_sentinel_outside_a_git_repo(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # repo_root (tmp_path) is genuinely not a git repository -- the real, uninjected
    # `_run_git` path (exercised the same way in test_locate.py's
    # test_run_git_against_a_real_non_repo_directory_returns_none) returns None here, so
    # _resolve_tree_sha's fallback sentinel is what actually reaches the printed prompt. No
    # existing test asserted this string ever appears in real output, only that *some* run
    # exercising the fallback branch doesn't crash.
    _make_change(repo_root, "demo-change")
    rc = main(["plan", "--repo", str(repo_root), "--change", "demo-change", "--force-path", "degraded"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "<unknown -- not a git repository or git unavailable>" in out


def test_plan_without_force_path_uses_real_detection(
    repo_root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    _make_change(repo_root, "demo-change")
    # No claude-foundation/ under repo_root at all -- detection must land on "degraded"
    # without --force-path forcing anything.
    rc = main(["plan", "--repo", str(repo_root), "--change", "demo-change", "--tree-sha", "abc123"])
    assert rc == 0
    assert "dispatch path: degraded" in capsys.readouterr().out


def test_plan_json_output_is_parseable(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _make_change(repo_root, "demo-change")
    rc = main(
        [
            "plan",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--force-path",
            "degraded",
            "--tree-sha",
            "abc123",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == "degraded"
    assert payload["prompts"][0]["subagent_type"] == "general-purpose"


def test_plan_out_dir_writes_prompt_files(repo_root: Path, tmp_path: Path) -> None:
    _make_change(repo_root, "demo-change")
    out_dir = tmp_path / "prompts"
    rc = main(
        [
            "plan",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--force-path",
            "plugin",
            "--tree-sha",
            "abc123",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert rc == 0
    assert (out_dir / "spec-guardian.md").is_file()
    assert (out_dir / "peer-reviewer.md").is_file()


# --- compose -----------------------------------------------------------------------------------


def test_compose_creates_review_from_body_file(
    repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_change(repo_root, "demo-change")
    body_file = tmp_path / "body.md"
    body_file.write_text(_GOOD_BODY, encoding="utf-8")

    rc = main(
        [
            "compose",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--body-file",
            str(body_file),
            "--tree-sha",
            "abc123",
            "--dispatch-path",
            "degraded",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "created:" in out
    review_path = repo_root / "openspec" / "changes" / "demo-change" / "review.md"
    assert review_path.is_file()
    assert review_path.read_text(encoding="utf-8").startswith("# Review: demo-change\n")


def test_compose_bogus_change_is_nonzero(repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(_GOOD_BODY, encoding="utf-8")
    rc = main(
        [
            "compose",
            "--repo",
            str(repo_root),
            "--change",
            "nope",
            "--body-file",
            str(body_file),
            "--dispatch-path",
            "degraded",
        ]
    )
    assert rc == 2
    assert "no such change" in capsys.readouterr().err


def test_compose_reports_structural_failure_with_nonzero_exit(
    repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_change(repo_root, "demo-change")
    body_file = tmp_path / "bad-body.md"
    body_file.write_text("no headings here at all\n", encoding="utf-8")

    rc = main(
        [
            "compose",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--body-file",
            str(body_file),
            "--dispatch-path",
            "degraded",
        ]
    )
    assert rc == 1
    assert "structural validation FAILED" in capsys.readouterr().err


def test_compose_json_output_is_parseable(repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression test: --json used to be silently ignored by `compose` (every other
    # subcommand honors it) -- a caller passing --json got the same plain text either way.
    _make_change(repo_root, "demo-change")
    body_file = tmp_path / "body.md"
    body_file.write_text(_GOOD_BODY, encoding="utf-8")

    rc = main(
        [
            "compose",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--body-file",
            str(body_file),
            "--tree-sha",
            "abc123",
            "--dispatch-path",
            "degraded",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "structural validation OK" not in out  # JSON mode replaces the text report entirely
    payload = json.loads(out)
    review_path = repo_root / "openspec" / "changes" / "demo-change" / "review.md"
    assert payload["mode"] == "created"
    assert payload["path"] == str(review_path)
    assert payload["validation"]["ok"] is True
    assert payload["validation"]["verdict"] == "APPROVE"


def test_compose_json_output_on_structural_failure_still_parses_and_reports_nonzero(
    repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_change(repo_root, "demo-change")
    body_file = tmp_path / "bad-body.md"
    body_file.write_text("no headings here at all\n", encoding="utf-8")

    rc = main(
        [
            "compose",
            "--repo",
            str(repo_root),
            "--change",
            "demo-change",
            "--body-file",
            str(body_file),
            "--dispatch-path",
            "degraded",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    payload = json.loads(out)  # still valid JSON on the failure path, exactly like `validate`
    assert payload["validation"]["ok"] is False
    assert payload["validation"]["errors"]


# --- validate ----------------------------------------------------------------------------------


def test_validate_by_explicit_path(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    path.write_text("# Review: demo\n\n" + _GOOD_BODY, encoding="utf-8")
    rc = main(["validate", "--path", str(path), "--change", "demo"])
    assert rc == 0


def test_validate_missing_file_is_nonzero(tmp_path: Path) -> None:
    rc = main(["validate", "--path", str(tmp_path / "nope.md")])
    assert rc == 1


def test_validate_requires_change_or_path(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["validate", "--repo", str(repo_root)])
    assert rc == 2
    assert "--path or --change" in capsys.readouterr().err


def test_validate_by_change_bogus_id_is_nonzero(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["validate", "--repo", str(repo_root), "--change", "nope"])
    assert rc == 2
    assert "no such change" in capsys.readouterr().err


def test_validate_by_change_resolves_its_own_review_path(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    change_dir = _make_change(repo_root, "demo-change")
    (change_dir / "review.md").write_text("# Review: demo-change\n\n" + _GOOD_BODY, encoding="utf-8")
    rc = main(["validate", "--repo", str(repo_root), "--change", "demo-change"])
    assert rc == 0
    assert "ok: True" in capsys.readouterr().out


def test_validate_json_output_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "review.md"
    path.write_text("# Review: demo\n\n" + _GOOD_BODY, encoding="utf-8")
    rc = main(["validate", "--path", str(path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["verdict"] == "APPROVE"


# --- full round trip through the CLI only (no library-level shortcuts) -----------------------


def test_full_round_trip_locate_plan_compose_validate(
    repo_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_change(repo_root, "round-trip-change")

    assert main(["locate", "--repo", str(repo_root), "--change", "round-trip-change"]) == 0
    capsys.readouterr()

    assert main(["plan", "--repo", str(repo_root), "--change", "round-trip-change", "--force-path", "degraded"]) == 0
    capsys.readouterr()

    body_file = tmp_path / "reviewer-output.md"
    body_file.write_text(_GOOD_BODY, encoding="utf-8")
    assert (
        main(
            [
                "compose",
                "--repo",
                str(repo_root),
                "--change",
                "round-trip-change",
                "--body-file",
                str(body_file),
                "--tree-sha",
                "cafef00d",
                "--dispatch-path",
                "degraded",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["validate", "--repo", str(repo_root), "--change", "round-trip-change"]) == 0

    # A second compose call against the same change must append, never clobber.
    second_body = tmp_path / "second.md"
    second_body.write_text(_GOOD_BODY, encoding="utf-8")
    assert (
        main(
            [
                "compose",
                "--repo",
                str(repo_root),
                "--change",
                "round-trip-change",
                "--body-file",
                str(second_body),
                "--dispatch-path",
                "degraded",
                "--date",
                "2026-09-01",
            ]
        )
        == 0
    )
    final_text = (repo_root / "openspec" / "changes" / "round-trip-change" / "review.md").read_text(encoding="utf-8")
    assert "cafef00d" in final_text  # first pass's reviewed-line survived
    assert "## Follow-up review -- 2026-09-01" in final_text
