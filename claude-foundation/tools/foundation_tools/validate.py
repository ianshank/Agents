"""Walk the plugin tree and validate every component against the pinned schemas.

Usage: ``python -m foundation_tools.validate [--root PATH]``

Exit codes: 0 all components valid; 1 findings; 2 usage/config error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from foundation_tools.frontmatter import FrontmatterError, load_frontmatter
from foundation_tools.jsonlog import get_logger
from foundation_tools.schemas import (
    AgentFrontmatter,
    EvalSuite,
    MarketplaceManifest,
    PluginManifest,
    SkillFrontmatter,
)

logger = get_logger("foundation.validate")

# .claude-plugin/ may contain ONLY the manifests; components live at plugin root.
_MANIFEST_ONLY = frozenset({"plugin.json", "marketplace.json"})


def _fmt_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
    )


def check_manifests(root: Path) -> list[str]:
    """Validate plugin.json + marketplace.json and the manifest-only layout rule."""
    errors: list[str] = []
    manifest_dir = root / ".claude-plugin"
    plugin_path = manifest_dir / "plugin.json"
    if not plugin_path.exists():
        return [f"{plugin_path.relative_to(root).as_posix()}: missing plugin manifest"]

    plugin_name = None
    try:
        manifest = PluginManifest.model_validate(json.loads(plugin_path.read_text("utf-8")))
        plugin_name = manifest.name
    except (json.JSONDecodeError, ValidationError) as exc:
        errors.append(
            f"plugin.json: {_fmt_validation_error(exc) if isinstance(exc, ValidationError) else exc}"
        )

    market_path = manifest_dir / "marketplace.json"
    if market_path.exists():
        try:
            market = MarketplaceManifest.model_validate(json.loads(market_path.read_text("utf-8")))
            if plugin_name and plugin_name not in {p.name for p in market.plugins}:
                errors.append(
                    f"marketplace.json: plugin '{plugin_name}' is not listed in its own marketplace"
                )
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(
                f"marketplace.json: {_fmt_validation_error(exc) if isinstance(exc, ValidationError) else exc}"
            )

    for entry in manifest_dir.iterdir():
        if entry.name not in _MANIFEST_ONLY:
            errors.append(
                f".claude-plugin/{entry.name}: only plugin.json/marketplace.json belong here; "
                "components live at the plugin root"
            )
    return errors


def check_skills(root: Path) -> list[str]:
    """Validate every SKILL.md frontmatter and its evals suite (>=3 cases)."""
    errors: list[str] = []
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return errors
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        rel = skill_dir.relative_to(root).as_posix()
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"{rel}: missing SKILL.md")
            continue
        try:
            front, _ = load_frontmatter(skill_md)
            fm = SkillFrontmatter.model_validate(front)
            if fm.name != skill_dir.name:
                errors.append(
                    f"{rel}: frontmatter name '{fm.name}' != directory '{skill_dir.name}'"
                )
        except FrontmatterError as exc:
            errors.append(f"{rel}/SKILL.md: {exc}")
        except ValidationError as exc:
            errors.append(f"{rel}/SKILL.md: {_fmt_validation_error(exc)}")

        evals_path = skill_dir / "evals" / "evals.json"
        if not evals_path.exists():
            errors.append(f"{rel}: missing evals/evals.json (every skill ships with evals)")
            continue
        try:
            suite = EvalSuite.model_validate(json.loads(evals_path.read_text("utf-8")))
            if suite.skill != skill_dir.name:
                errors.append(f"{rel}/evals: suite skill '{suite.skill}' != directory")
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(
                f"{rel}/evals/evals.json: "
                f"{_fmt_validation_error(exc) if isinstance(exc, ValidationError) else exc}"
            )
    return errors


def check_agents(root: Path) -> list[str]:
    """Validate every agents/*.md frontmatter (plugin-honored fields only)."""
    errors: list[str] = []
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return errors
    for agent_md in sorted(agents_dir.rglob("*.md")):
        rel = agent_md.relative_to(root).as_posix()
        try:
            front, _ = load_frontmatter(agent_md)
            fm = AgentFrontmatter.model_validate(front)
            if fm.name != agent_md.stem:
                errors.append(f"{rel}: frontmatter name '{fm.name}' != filename '{agent_md.stem}'")
        except FrontmatterError as exc:
            errors.append(f"{rel}: {exc}")
        except ValidationError as exc:
            errors.append(f"{rel}: {_fmt_validation_error(exc)}")
    return errors


def check_hooks(root: Path) -> list[str]:
    """Validate hooks/hooks.json structure and that commands stay portable."""
    errors: list[str] = []
    hooks_path = root / "hooks" / "hooks.json"
    if not hooks_path.exists():
        return errors
    try:
        config = json.loads(hooks_path.read_text("utf-8"))
    except json.JSONDecodeError as exc:
        return [f"hooks/hooks.json: {exc}"]
    if not isinstance(config, dict):
        return ["hooks/hooks.json: must be a JSON object"]
    hooks_map = config.get("hooks", config)
    if not isinstance(hooks_map, dict):
        return ["hooks/hooks.json: top-level 'hooks' must be a mapping of event -> matchers"]
    for event, matchers in hooks_map.items():
        if not isinstance(matchers, list):
            errors.append(f"hooks/hooks.json[{event}]: expected a list of matcher blocks")
            continue
        for block in matchers:
            if not isinstance(block, dict):
                errors.append(f"hooks/hooks.json[{event}]: each matcher block must be an object")
                continue
            hooks_list = block.get("hooks", [])
            if not isinstance(hooks_list, list):
                errors.append(f"hooks/hooks.json[{event}]: 'hooks' must be a list")
                continue
            for hook in hooks_list:
                command = hook.get("command", "") if isinstance(hook, dict) else ""
                if "${CLAUDE_PLUGIN_ROOT}" not in command:
                    errors.append(
                        f"hooks/hooks.json[{event}]: command must reference scripts via "
                        f"${{CLAUDE_PLUGIN_ROOT}} (got: {command!r})"
                    )
    return errors


def validate_tree(root: Path) -> list[str]:
    """Run every component check; returns the combined finding list."""
    findings: list[str] = []
    for check in (check_manifests, check_skills, check_agents, check_hooks):
        found = check(root)
        findings.extend(found)
        logger.info("check complete", extra={"check": check.__name__, "findings": len(found)})
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="plugin root (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    findings = validate_tree(root)
    if findings:
        print("VALIDATION FAILED:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("foundation-validate: OK — all components valid")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
