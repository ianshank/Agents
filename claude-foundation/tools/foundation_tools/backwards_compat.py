"""Enforce append-only component names across a major version (ADR 0001 pt. 4; ADR 0004).

Diffs the plugin's live public surface (skill names, subagent names, hook script
names) against a checked-in baseline (``tests/backwards_compat_baseline.json``).
A component missing from the live tree that was present in the baseline is a
finding unless ``plugin.json``'s major version has increased since the baseline
was last frozen — renames/removals are only permitted alongside a major bump.
Additions never produce a finding; they simply mean the baseline is due for a
refresh before the next release (see ``--update``).

Usage: ``python -m foundation_tools.backwards_compat [--root PATH] [--baseline-path PATH] [--update]``
Exit codes: 0 gate passes; 1 findings; 2 usage/config error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from foundation_tools.frontmatter import FrontmatterError, load_frontmatter
from foundation_tools.jsonlog import get_logger
from foundation_tools.schemas import AgentFrontmatter, PluginManifest, SkillFrontmatter

logger = get_logger("foundation.backwards_compat")

# Relative to the plugin root being checked (the --root argument), never to this
# module's own location — a module-anchored path would silently check a *different*
# plugin's live tree against *this* repo's baseline if --root ever pointed elsewhere
# (e.g. this package installed into, or reused against, a sibling plugin repo).
_BASELINE_DIR_NAME = "tests"
_BASELINE_FILENAME = "backwards_compat_baseline.json"
_PLUGIN_MANIFEST_REL = Path(".claude-plugin") / "plugin.json"
_HOOK_SCRIPT_RE = re.compile(r"([A-Za-z0-9_.-]+\.py)")


def default_baseline_path(root: Path) -> Path:
    """The baseline location for a given plugin root: ``<root>/tests/<filename>``."""
    return root / _BASELINE_DIR_NAME / _BASELINE_FILENAME


def _extract_skills(root: Path) -> list[str]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return []
    names: list[str] = []
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            front, _ = load_frontmatter(skill_md)
            names.append(SkillFrontmatter.model_validate(front).name)
        except (FrontmatterError, ValidationError, OSError):
            names.append(skill_dir.name)
    return names


def _extract_agents(root: Path) -> list[str]:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return []
    names: list[str] = []
    for agent_md in sorted(agents_dir.rglob("*.md")):
        try:
            front, _ = load_frontmatter(agent_md)
            names.append(AgentFrontmatter.model_validate(front).name)
        except (FrontmatterError, ValidationError, OSError):
            names.append(agent_md.stem)
    return names


def _hook_script_names(hooks_config: dict[str, Any]) -> set[str]:
    """Extract the stable script-basename identity of every registered hook.

    ``hooks.json`` has no per-hook name field, so the script basename referenced
    in each matcher's ``command`` is used as component identity (matches the
    convention in docs/architecture.md's hook table). A script may legitimately
    be registered under more than one event/matcher; results are deduped via
    a set rather than assuming a 1:1 script-to-matcher mapping.
    """
    names: set[str] = set()
    hooks_map = hooks_config.get("hooks", hooks_config)
    if not isinstance(hooks_map, dict):
        return names
    for matchers in hooks_map.values():
        if not isinstance(matchers, list):
            continue
        for block in matchers:
            if not isinstance(block, dict):
                continue
            for hook in block.get("hooks", []):
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                match = _HOOK_SCRIPT_RE.search(command)
                if match:
                    names.add(match.group(1))
    return names


def _extract_hooks(root: Path) -> list[str]:
    hooks_path = root / "hooks" / "hooks.json"
    if not hooks_path.exists():
        return []
    try:
        config = json.loads(hooks_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(config, dict):
        return []
    return sorted(_hook_script_names(config))


def extract_surface(root: Path) -> dict[str, list[str]]:
    """Return the live plugin's public surface: ``{kind: sorted(component names)}``.

    General-purpose by design — a future component kind (MCP servers, LSP
    configs) is a one-branch addition here, not a new module. Sorted explicitly
    here (not left to each ``_extract_*`` helper) since frontmatter ``name`` can
    differ from filesystem traversal order — e.g. directory ``aaa`` declaring
    ``name: zzz`` — so directory-sorted iteration alone wouldn't guarantee
    name-sorted output.
    """
    return {
        "skills": sorted(_extract_skills(root)),
        "agents": sorted(_extract_agents(root)),
        "hooks": _extract_hooks(root),  # already sorted: built from a set
    }


def diff_surface(
    baseline: dict[str, list[str]], current: dict[str, list[str]]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return ``(removed, added)`` per component kind. Pure — no filesystem access."""
    removed: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    for kind in sorted(set(baseline) | set(current)):
        base_set = set(baseline.get(kind, []))
        cur_set = set(current.get(kind, []))
        dropped = sorted(base_set - cur_set)
        gained = sorted(cur_set - base_set)
        if dropped:
            removed[kind] = dropped
        if gained:
            added[kind] = gained
    return removed, added


def _load_baseline(baseline_path: Path) -> dict[str, Any] | None:
    if not baseline_path.exists():
        return None
    data = json.loads(baseline_path.read_text("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("baseline must be a JSON object")
    return data


def _validated_recorded_major(baseline: dict[str, Any]) -> int:
    value = baseline.get("recorded_major_version", 0)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("baseline 'recorded_major_version' must be an integer")
    return value


def _validated_components(baseline: dict[str, Any]) -> dict[str, list[str]]:
    components = baseline.get("components", {})
    if not isinstance(components, dict):
        raise ValueError("baseline 'components' must be an object")
    validated: dict[str, list[str]] = {}
    for kind, names in components.items():
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise ValueError(f"baseline components[{kind!r}] must be a list of strings")
        validated[kind] = names
    return validated


def _read_manifest(root: Path) -> PluginManifest:
    plugin_path = root / _PLUGIN_MANIFEST_REL
    return PluginManifest.model_validate(json.loads(plugin_path.read_text("utf-8")))


def _current_major(root: Path) -> int:
    return int(_read_manifest(root).version.split(".", 1)[0])


def check_backwards_compat(root: Path, *, baseline_path: Path | None = None) -> list[str]:
    """Return findings: components removed from the live tree without a major bump."""
    if baseline_path is None:
        baseline_path = default_baseline_path(root)
    try:
        baseline = _load_baseline(baseline_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"{baseline_path}: unreadable baseline ({exc})"]
    if baseline is None:
        return [f"{baseline_path}: no baseline found; run --update to create one"]

    try:
        recorded_major = _validated_recorded_major(baseline)
        baseline_components = _validated_components(baseline)
    except ValueError as exc:
        return [f"{baseline_path}: malformed baseline ({exc})"]

    try:
        current_major = _current_major(root)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        return [f"{_PLUGIN_MANIFEST_REL}: {exc} (cannot verify major-version exception)"]

    major_bumped = current_major > recorded_major

    current = extract_surface(root)
    removed, added = diff_surface(baseline_components, current)

    findings: list[str] = []
    if removed and not major_bumped:
        for kind, names in removed.items():
            findings.append(
                f"{kind}: removed without a major version bump (baseline major "
                f"{recorded_major}, current {current_major}): {names}"
            )
    logger.info(
        "backwards-compat check complete",
        extra={"removed": removed, "added": added, "major_bumped": major_bumped},
    )
    if added:
        logger.info("components added since baseline was frozen", extra={"added": added})
    if major_bumped:
        # Baseline still reflects the pre-bump major. Non-failing: a component
        # added after the bump and removed before the next --update would never
        # be captured as a removal, so surface this as a visible warning rather
        # than silently accepting the blind spot.
        logger.warning(
            "baseline not refreshed since last major version bump; run --update",
            extra={"baseline_major": recorded_major, "current_major": current_major},
        )
    return findings


def backwards_compat_tree(root: Path, *, baseline_path: Path | None = None) -> list[str]:
    """Aggregator entry point, mirrors validate_tree/scan_tree naming."""
    findings = check_backwards_compat(root, baseline_path=baseline_path)
    logger.info("check complete", extra={"check": "backwards_compat", "findings": len(findings)})
    return findings


def _update_baseline(root: Path, baseline_path: Path | None = None) -> None:
    if baseline_path is None:
        baseline_path = default_baseline_path(root)
    manifest = _read_manifest(root)
    current_major = int(manifest.version.split(".", 1)[0])
    surface = extract_surface(root)
    payload = {
        "plugin_name": manifest.name,
        "recorded_major_version": current_major,
        "components": {kind: sorted(names) for kind, names in surface.items()},
    }
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="plugin root (default: cwd)")
    parser.add_argument(
        "--baseline-path",
        default=None,
        help=(
            "override the baseline file location "
            "(default: <root>/tests/backwards_compat_baseline.json)"
        ),
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="regenerate the baseline from the live tree (run before tagging a release)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline_path).resolve() if args.baseline_path else None

    if args.update:
        try:
            _update_baseline(root, baseline_path)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            print(f"could not update baseline: {exc}", file=sys.stderr)
            return 2
        print("foundation-backwards-compat: baseline updated")
        return 0

    findings = backwards_compat_tree(root, baseline_path=baseline_path)
    if findings:
        print("BACKWARDS-COMPAT GATE FAILED:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("foundation-backwards-compat: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
