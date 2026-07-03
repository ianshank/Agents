from __future__ import annotations

from pathlib import Path

import pytest

from foundation_tools import scan as fs


def test_clean_tree_passes(plugin_tree: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fs.scan_tree(plugin_tree) == []
    assert fs.main(["--root", str(plugin_tree)]) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("payload", "rule"),
    [
        ("model = 'claude-" + "opus-4-8'", "full-model-id"),
        ("key = 'AKIA" + "ABCDEFGHIJKLMNOP'", "aws-access-key"),
        ("token = 'sk-" + "a" * 24 + "'", "api-key-literal"),
        ("t = 'ghp_" + "b" * 24 + "'", "github-token"),
        ('api_key = "hunter2secret"', "assigned-secret"),
        ('path = "/home/someone/project/config.yaml"', "absolute-path"),
        ("model = 'Claude-" + "Sonnet-4-5'", "full-model-id"),  # case-insensitive
        ("api_key = mysecretvalue123", "assigned-secret"),  # unquoted
        ('secret_key="realvalue123"', "assigned-secret"),  # underscore keyword
        ("x = '/root/private/thing'", "absolute-path"),  # widened root
    ],
)
def test_each_rule_fires(plugin_tree: Path, payload: str, rule: str) -> None:
    (plugin_tree / "hooks" / "bad.py").write_text(payload + "\n", encoding="utf-8")
    findings = fs.scan_tree(plugin_tree)
    assert any(rule in f for f in findings), findings


def test_env_placeholders_are_not_flagged(plugin_tree: Path) -> None:
    (plugin_tree / "hooks" / "ok.py").write_text(
        'token = "${API_TOKEN}"\nkey = "$SECRET"\n', encoding="utf-8"
    )
    assert fs.scan_tree(plugin_tree) == []


def test_scan_allow_waiver_suppresses_but_logs(
    plugin_tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (plugin_tree / "hooks" / "waived.py").write_text(
        "EXAMPLE = 'claude-" + "opus-4-8'  # scan:allow — doc example\n", encoding="utf-8"
    )
    # The scan logger sets propagate=False, so attach caplog's handler directly.
    fs.logger.addHandler(caplog.handler)
    try:
        assert fs.scan_tree(plugin_tree) == []
    finally:
        fs.logger.removeHandler(caplog.handler)
    # M6: waivers are never silent — the waived location is logged with its rules.
    waivers = [r for r in caplog.records if r.message == "waiver"]
    assert waivers and getattr(waivers[0], "rules", None) == ["full-model-id"]


def test_env_exclude_globs(plugin_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (plugin_tree / "hooks" / "vendored.py").write_text(
        'p = "/usr/local/vendored/thing"\n', encoding="utf-8"
    )
    assert fs.scan_tree(plugin_tree) != []
    monkeypatch.setenv(fs.SCAN_EXCLUDE_ENV, "hooks/vendored.py")
    assert fs.scan_tree(plugin_tree) == []


def test_example_files_and_docs_are_exempt(plugin_tree: Path) -> None:
    (plugin_tree / ".mcp.json.example").write_text(
        '{"cmd": "/opt/example/server"}\n', encoding="utf-8"
    )
    docs = plugin_tree / "skills" / "hello" / "docs"
    assert fs.scan_tree(plugin_tree) == []
    assert docs.exists() is False  # docs/* default exclusion is root-relative


def test_mcp_json_is_in_scope(plugin_tree: Path) -> None:
    (plugin_tree / ".mcp.json").write_text('{"cmd": "/opt/real/server"}\n', encoding="utf-8")
    findings = fs.scan_tree(plugin_tree)
    assert any(".mcp.json" in f and "absolute-path" in f for f in findings)


def test_main_reports_findings(plugin_tree: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (plugin_tree / "hooks" / "bad.py").write_text('x = "/etc/passwd"\n', encoding="utf-8")
    assert fs.main(["--root", str(plugin_tree)]) == 1
    assert "HARDCODE SCAN FAILED" in capsys.readouterr().out
    assert fs.main(["--root", str(plugin_tree / "nope")]) == 2
