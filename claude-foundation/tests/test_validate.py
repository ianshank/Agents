from __future__ import annotations

import json
from pathlib import Path

from foundation_tools import validate as fv


def test_valid_tree_passes(plugin_tree: Path) -> None:
    assert fv.validate_tree(plugin_tree) == []


def test_main_exit_codes(plugin_tree: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert fv.main(["--root", str(plugin_tree)]) == 0
    assert "OK" in capsys.readouterr().out
    (plugin_tree / "skills" / "hello" / "evals" / "evals.json").unlink()
    assert fv.main(["--root", str(plugin_tree)]) == 1
    assert "VALIDATION FAILED" in capsys.readouterr().out
    assert fv.main(["--root", str(plugin_tree / "does-not-exist")]) == 2


def test_manifest_only_layout_rule(plugin_tree: Path) -> None:
    (plugin_tree / ".claude-plugin" / "extra.txt").write_text("x", encoding="utf-8")
    findings = fv.validate_tree(plugin_tree)
    assert any("only plugin.json/marketplace.json" in f for f in findings)


def test_missing_plugin_manifest(plugin_tree: Path) -> None:
    (plugin_tree / ".claude-plugin" / "plugin.json").unlink()
    findings = fv.validate_tree(plugin_tree)
    assert any("missing plugin manifest" in f for f in findings)


def test_marketplace_must_list_own_plugin(plugin_tree: Path) -> None:
    market = plugin_tree / ".claude-plugin" / "marketplace.json"
    data = json.loads(market.read_text())
    data["plugins"][0]["name"] = "other"
    market.write_text(json.dumps(data), encoding="utf-8")
    findings = fv.validate_tree(plugin_tree)
    assert any("not listed in its own marketplace" in f for f in findings)


def test_skill_name_must_match_directory(plugin_tree: Path) -> None:
    skill_md = plugin_tree / "skills" / "hello" / "SKILL.md"
    skill_md.write_text("---\nname: goodbye\ndescription: mismatch\n---\nbody\n", encoding="utf-8")
    findings = fv.validate_tree(plugin_tree)
    assert any("!= directory 'hello'" in f for f in findings)


def test_skill_over_description_budget_is_flagged(plugin_tree: Path) -> None:
    skill_md = plugin_tree / "skills" / "hello" / "SKILL.md"
    skill_md.write_text(
        f"---\nname: hello\ndescription: {'d' * 1600}\n---\nbody\n", encoding="utf-8"
    )
    findings = fv.validate_tree(plugin_tree)
    assert any("budget" in f for f in findings)


def test_missing_evals_is_flagged(plugin_tree: Path) -> None:
    (plugin_tree / "skills" / "hello" / "evals" / "evals.json").unlink()
    findings = fv.validate_tree(plugin_tree)
    assert any("missing evals/evals.json" in f for f in findings)


def test_agent_with_ignored_plugin_fields_is_flagged(plugin_tree: Path) -> None:
    agent = plugin_tree / "agents" / "scout.md"
    agent.write_text(
        "---\nname: scout\ndescription: d\npermissionMode: auto\n---\nbody\n",
        encoding="utf-8",
    )
    findings = fv.validate_tree(plugin_tree)
    assert any("agents/scout.md" in f for f in findings)


def test_agent_name_must_match_filename(plugin_tree: Path) -> None:
    agent = plugin_tree / "agents" / "scout.md"
    agent.write_text("---\nname: ranger\ndescription: d\n---\nbody\n", encoding="utf-8")
    findings = fv.validate_tree(plugin_tree)
    assert any("!= filename 'scout'" in f for f in findings)


def test_hook_command_must_use_plugin_root(plugin_tree: Path) -> None:
    hooks = plugin_tree / "hooks" / "hooks.json"
    hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [{"type": "command", "command": "python3 guard.py"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    findings = fv.validate_tree(plugin_tree)
    assert any("CLAUDE_PLUGIN_ROOT" in f for f in findings)


def test_unreadable_hooks_json(plugin_tree: Path) -> None:
    (plugin_tree / "hooks" / "hooks.json").write_text("{not json", encoding="utf-8")
    findings = fv.validate_tree(plugin_tree)
    assert any("hooks/hooks.json" in f for f in findings)
