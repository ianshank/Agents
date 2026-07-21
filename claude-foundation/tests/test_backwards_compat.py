from __future__ import annotations

import json
import logging
from pathlib import Path

from foundation_tools import backwards_compat as bc

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_baseline(path: Path, *, major: int, components: dict[str, list[str]]) -> None:
    path.write_text(
        json.dumps(
            {"plugin_name": "demo", "recorded_major_version": major, "components": components}
        ),
        encoding="utf-8",
    )


def _live_surface(plugin_tree: Path) -> dict[str, list[str]]:
    return bc.extract_surface(plugin_tree)


def _set_plugin_version(plugin_tree: Path, version: str) -> None:
    manifest_path = plugin_tree / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest_path.read_text())
    data["version"] = version
    manifest_path.write_text(json.dumps(data), encoding="utf-8")


def test_matching_baseline_passes(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components=_live_surface(plugin_tree))
    assert bc.check_backwards_compat(plugin_tree, baseline_path=baseline) == []


def test_removed_skill_without_bump_fails(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    components = _live_surface(plugin_tree)
    components["skills"].append("legacy")
    _write_baseline(baseline, major=1, components=components)
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("legacy" in f and "skills" in f for f in findings)


def test_removed_agent_without_bump_fails(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    components = _live_surface(plugin_tree)
    components["agents"].append("ranger")
    _write_baseline(baseline, major=1, components=components)
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("ranger" in f and "agents" in f for f in findings)


def test_removed_hook_without_bump_fails(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    components = _live_surface(plugin_tree)
    components["hooks"].append("old_hook.py")
    _write_baseline(baseline, major=1, components=components)
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("old_hook.py" in f and "hooks" in f for f in findings)


def test_removal_allowed_with_major_bump(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    components = _live_surface(plugin_tree)
    components["skills"].append("legacy")
    _write_baseline(baseline, major=1, components=components)
    _set_plugin_version(plugin_tree, "2.0.0")
    assert bc.check_backwards_compat(plugin_tree, baseline_path=baseline) == []


def test_added_component_is_not_a_failure(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components={"skills": [], "agents": [], "hooks": []})
    assert bc.check_backwards_compat(plugin_tree, baseline_path=baseline) == []


def test_main_exit_codes(plugin_tree: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components=_live_surface(plugin_tree))

    assert bc.main(["--root", str(plugin_tree), "--baseline-path", str(baseline)]) == 0
    assert "OK" in capsys.readouterr().out

    components = _live_surface(plugin_tree)
    components["skills"].append("legacy")
    _write_baseline(baseline, major=1, components=components)
    assert bc.main(["--root", str(plugin_tree), "--baseline-path", str(baseline)]) == 1
    assert "BACKWARDS-COMPAT GATE FAILED" in capsys.readouterr().out

    assert bc.main(["--root", str(plugin_tree / "does-not-exist")]) == 2


def test_update_flow_regenerates_baseline(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    assert bc.main(["--root", str(plugin_tree), "--baseline-path", str(baseline), "--update"]) == 0

    data = json.loads(baseline.read_text())
    assert data["components"] == _live_surface(plugin_tree)
    assert data["recorded_major_version"] == 1


def test_default_baseline_path_is_derived_from_root(plugin_tree: Path) -> None:
    """The default baseline location tracks --root, not this module's own file location.

    A module-anchored default would silently check a *different* plugin's live tree
    against *this* repo's baseline if --root ever pointed elsewhere; deriving it from
    root instead means the same command is correct for any plugin checkout.
    """
    assert (
        bc.default_baseline_path(plugin_tree)
        == plugin_tree / "tests" / "backwards_compat_baseline.json"
    )

    (plugin_tree / "tests").mkdir()
    _write_baseline(
        plugin_tree / "tests" / "backwards_compat_baseline.json",
        major=1,
        components=_live_surface(plugin_tree),
    )
    # No --baseline-path: resolved from --root alone.
    assert bc.main(["--root", str(plugin_tree)]) == 0


def test_update_without_baseline_path_writes_to_default_location(plugin_tree: Path) -> None:
    assert bc.main(["--root", str(plugin_tree), "--update"]) == 0
    default_path = plugin_tree / "tests" / "backwards_compat_baseline.json"
    assert default_path.exists()
    assert json.loads(default_path.read_text())["components"] == _live_surface(plugin_tree)


def test_malformed_plugin_json_is_a_finding_not_a_crash(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components=_live_surface(plugin_tree))
    (plugin_tree / ".claude-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("plugin.json" in f for f in findings)


def test_missing_baseline_is_a_finding_not_a_crash(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "does-not-exist.json"
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("no baseline found" in f for f in findings)


def test_zero_component_tree_does_not_crash(tmp_path: Path) -> None:
    root = tmp_path / "empty-plugin"
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "empty", "version": "1.0.0"}), encoding="utf-8"
    )
    assert bc.extract_surface(root) == {"skills": [], "agents": [], "hooks": []}

    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components={"skills": [], "agents": [], "hooks": []})
    assert bc.check_backwards_compat(root, baseline_path=baseline) == []


def test_diff_surface_pure() -> None:
    assert bc.diff_surface({"skills": ["a"]}, {"skills": ["a"]}) == ({}, {})
    assert bc.diff_surface({"skills": ["a", "b"]}, {"skills": ["a"]}) == (
        {"skills": ["b"]},
        {},
    )
    assert bc.diff_surface({"skills": ["a"]}, {"skills": ["a", "b"]}) == (
        {},
        {"skills": ["b"]},
    )
    assert bc.diff_surface(
        {"skills": ["a"], "agents": ["x"]}, {"skills": ["b"], "agents": ["x", "y"]}
    ) == ({"skills": ["a"]}, {"skills": ["b"], "agents": ["y"]})


def test_staleness_warning_logged_without_failing(  # type: ignore[no-untyped-def]
    plugin_tree: Path, tmp_path: Path, caplog
) -> None:
    baseline = tmp_path / "baseline.json"
    _write_baseline(baseline, major=1, components=_live_surface(plugin_tree))
    _set_plugin_version(plugin_tree, "2.0.0")
    with caplog.at_level(logging.WARNING, logger="foundation.backwards_compat"):
        findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert findings == []
    assert any("not refreshed" in record.message for record in caplog.records)


def test_nested_agent_directory_is_discovered(plugin_tree: Path) -> None:
    nested = plugin_tree / "agents" / "sub"
    nested.mkdir()
    (nested / "nested.md").write_text(
        "---\nname: nested\ndescription: d\n---\nbody\n", encoding="utf-8"
    )
    surface = bc.extract_surface(plugin_tree)
    assert "nested" in surface["agents"]


def test_real_repo_baseline_matches_real_tree() -> None:
    assert bc.check_backwards_compat(REPO_ROOT) == []


def test_skill_frontmatter_parse_failure_falls_back_to_directory_name(plugin_tree: Path) -> None:
    skill_md = plugin_tree / "skills" / "hello" / "SKILL.md"
    skill_md.write_text("not frontmatter at all", encoding="utf-8")
    assert "hello" in bc.extract_surface(plugin_tree)["skills"]


def test_agent_frontmatter_parse_failure_falls_back_to_filename(plugin_tree: Path) -> None:
    agent_md = plugin_tree / "agents" / "scout.md"
    agent_md.write_text("not frontmatter at all", encoding="utf-8")
    assert "scout" in bc.extract_surface(plugin_tree)["agents"]


def test_hooks_json_malformed_shapes_do_not_crash(plugin_tree: Path) -> None:
    hooks_path = plugin_tree / "hooks" / "hooks.json"

    hooks_path.write_text("{not json", encoding="utf-8")
    assert bc.extract_surface(plugin_tree)["hooks"] == []

    hooks_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert bc.extract_surface(plugin_tree)["hooks"] == []

    hooks_path.write_text(json.dumps({"hooks": {"PreToolUse": ["not-a-dict"]}}), encoding="utf-8")
    assert bc.extract_surface(plugin_tree)["hooks"] == []

    hooks_path.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"hooks": "not-a-list"}]}}), encoding="utf-8"
    )
    assert bc.extract_surface(plugin_tree)["hooks"] == []


def test_missing_hooks_json_yields_no_hooks(plugin_tree: Path) -> None:
    (plugin_tree / "hooks" / "hooks.json").unlink()
    assert bc.extract_surface(plugin_tree)["hooks"] == []


def test_hooks_map_not_a_dict_yields_no_hooks(plugin_tree: Path) -> None:
    hooks_path = plugin_tree / "hooks" / "hooks.json"
    hooks_path.write_text(json.dumps({"hooks": "not-a-dict"}), encoding="utf-8")
    assert bc.extract_surface(plugin_tree)["hooks"] == []


def test_hooks_event_value_not_a_list_is_skipped(plugin_tree: Path) -> None:
    hooks_path = plugin_tree / "hooks" / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": "not-a-list",
                    "PostToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/session_logger.py"'
                                    ),
                                }
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    assert bc.extract_surface(plugin_tree)["hooks"] == ["session_logger.py"]


def test_skill_directory_without_skill_md_is_skipped(plugin_tree: Path) -> None:
    empty_skill_dir = plugin_tree / "skills" / "no-skill-md"
    empty_skill_dir.mkdir()
    assert "no-skill-md" not in bc.extract_surface(plugin_tree)["skills"]


def test_unreadable_baseline_is_a_finding_not_a_crash(plugin_tree: Path, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{not json", encoding="utf-8")
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("unreadable baseline" in f for f in findings)


def test_baseline_that_is_valid_json_but_not_an_object_is_a_finding(
    plugin_tree: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("unreadable baseline" in f and "JSON object" in f for f in findings)


def test_baseline_with_non_integer_major_is_a_finding_not_a_crash(
    plugin_tree: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "plugin_name": "demo",
                "recorded_major_version": "one",
                "components": _live_surface(plugin_tree),
            }
        ),
        encoding="utf-8",
    )
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("malformed baseline" in f and "recorded_major_version" in f for f in findings)


def test_baseline_with_non_object_components_is_a_finding_not_a_crash(
    plugin_tree: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"plugin_name": "demo", "recorded_major_version": 1, "components": "nope"}),
        encoding="utf-8",
    )
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("malformed baseline" in f and "components" in f for f in findings)


def test_baseline_with_non_list_component_kind_is_a_finding_not_a_crash(
    plugin_tree: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "plugin_name": "demo",
                "recorded_major_version": 1,
                "components": {"skills": "hello", "agents": [], "hooks": []},
            }
        ),
        encoding="utf-8",
    )
    findings = bc.check_backwards_compat(plugin_tree, baseline_path=baseline)
    assert any("malformed baseline" in f and "skills" in f for f in findings)


def test_extract_surface_returns_name_sorted_lists_even_when_frontmatter_reorders(
    plugin_tree: Path,
) -> None:
    """A skill directory sorted first can still declare a frontmatter name sorted
    last; extract_surface must sort by the returned name, not by directory order."""
    reordering_skill = plugin_tree / "skills" / "aaa-reorders-last"
    (reordering_skill / "evals").mkdir(parents=True)
    reordering_skill_md = reordering_skill / "SKILL.md"
    reordering_skill_md.write_text(
        "---\nname: zzz-actually-last\ndescription: reorders.\n---\n\nBody.\n",
        encoding="utf-8",
    )
    surface = bc.extract_surface(plugin_tree)
    assert surface["skills"] == sorted(surface["skills"])
    assert "zzz-actually-last" in surface["skills"]


def test_update_flow_reports_error_on_malformed_plugin_json(  # type: ignore[no-untyped-def]
    plugin_tree: Path, tmp_path: Path, capsys
) -> None:
    baseline = tmp_path / "baseline.json"
    (plugin_tree / ".claude-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")
    assert bc.main(["--root", str(plugin_tree), "--baseline-path", str(baseline), "--update"]) == 2
    assert "could not update baseline" in capsys.readouterr().err
