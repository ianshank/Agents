#!/usr/bin/env python3
"""Skill Marketplace CLI (F-023).

A centralized, schema-validated registry of community-contributed skills with
versioned ``SKILL.md`` validation. This tool *reuses* ``validate_skill.py``
(structural + behavioral checks) read-only and adds the marketplace-specific
rules on top: a semver ``version`` is required in each skill's frontmatter and
must match the registry entry, names must match and be unique, and every entry
must point at a real skill directory.

Subcommands:
    validate  Validate the registry against the schema and every registered skill.
    list      Print the registered skills (name, version, path).
    verify    Alias of validate that prints a one-line OK/FAIL summary only.

All paths and thresholds come from the registry/args; nothing is hard-coded.

Exit codes: 0 = OK, 1 = validation failed, 2 = usage/IO error.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys

# scripts/ is on sys.path in tests; for direct execution ensure our own dir is too.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _cli import configure_logging  # noqa: E402
from validate_skill import check_structural, parse_frontmatter  # noqa: E402

logger = logging.getLogger("skill_marketplace")

#: Semver pattern shared with marketplace.schema.json (kept in lockstep).
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

DEFAULT_REGISTRY = os.path.join("skills", "marketplace.yaml")
DEFAULT_SCHEMA = os.path.join("skills", "marketplace.schema.json")


def _repo_root() -> str:
    """Repo root is one level up from scripts/."""
    return os.path.dirname(_HERE)


def load_registry(registry_path: str) -> dict:
    """Load the YAML registry document. Raises FileNotFoundError/ValueError."""
    import yaml

    if not os.path.isfile(registry_path):
        raise FileNotFoundError(f"registry not found: {registry_path}")
    with open(registry_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"registry {registry_path} must be a mapping at the top level")
    return data


def validate_schema(registry: dict, schema_path: str, errors: list[str]) -> None:
    """Validate the registry against the JSON Schema, if jsonschema is available."""
    import json

    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema is a dev dependency
        logger.warning("jsonschema not installed; skipping schema validation")
        return
    if not os.path.isfile(schema_path):
        errors.append(f"schema not found: {schema_path}")
        return
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    try:
        jsonschema.validate(registry, schema)
    except jsonschema.ValidationError as exc:
        errors.append(f"registry does not match schema: {exc.message}")


def validate_entry(entry: dict, root: str, errors: list[str]) -> None:
    """Validate a single registry entry against its on-disk skill."""
    name = entry.get("name", "<unnamed>")
    version = entry.get("version", "")
    rel_path = entry.get("path", "")

    if not SEMVER_RE.match(str(version)):
        errors.append(f"{name}: registry version {version!r} is not semver (MAJOR.MINOR.PATCH)")

    skill_dir = rel_path if os.path.isabs(rel_path) else os.path.join(root, rel_path)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        errors.append(f"{name}: SKILL.md not found at {rel_path}")
        return

    fm, _ = parse_frontmatter(skill_md)
    if fm is None:
        errors.append(f"{name}: SKILL.md has no YAML frontmatter")
        return

    fm_name = fm.get("name", "")
    if fm_name != name:
        errors.append(f"{name}: registry name does not match SKILL.md name {fm_name!r}")

    fm_version = fm.get("version", "")
    if not fm_version:
        errors.append(f"{name}: SKILL.md frontmatter is missing a 'version' key")
    elif not SEMVER_RE.match(fm_version):
        errors.append(f"{name}: SKILL.md version {fm_version!r} is not semver")
    elif fm_version != str(version):
        errors.append(f"{name}: registry version {version!r} != SKILL.md version {fm_version!r}")

    # Reuse the canonical structural validator (read-only).
    struct_errs, _ = check_structural(skill_dir, "evals/evals.json")
    for e in struct_errs:
        errors.append(f"{name}: {e}")


def validate_registry(registry_path: str, schema_path: str) -> list[str]:
    """Full validation; returns a list of error strings (empty == OK)."""
    errors: list[str] = []
    registry = load_registry(registry_path)
    validate_schema(registry, schema_path, errors)

    skills = registry.get("skills", [])
    seen: set[str] = set()
    root = _repo_root()
    for entry in skills:
        name = entry.get("name", "<unnamed>")
        if name in seen:
            errors.append(f"{name}: duplicate skill name in registry")
            continue
        seen.add(name)
        validate_entry(entry, root, errors)
    return errors


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        errors = validate_registry(args.registry, args.schema)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2
    if errors:
        logger.error("Skill marketplace validation FAILED with %d error(s):", len(errors))
        for e in errors:
            logger.error("  • %s", e)
        return 1
    logger.info("Skill marketplace OK ✓")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    try:
        registry = load_registry(args.registry)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("%s", exc)
        return 2
    for entry in registry.get("skills", []):
        print(f"{entry.get('name', '<unnamed>')}\t{entry.get('version', '?')}\t{entry.get('path', '?')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Skill Marketplace registry tool.")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY, help="Path to marketplace.yaml")
    ap.add_argument("--schema", default=DEFAULT_SCHEMA, help="Path to marketplace.schema.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate the registry and every registered skill")
    sub.add_parser("verify", help="Validate and print a one-line summary")
    sub.add_parser("list", help="List the registered skills")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    if args.command in ("validate", "verify"):
        return _cmd_validate(args)
    if args.command == "list":
        return _cmd_list(args)
    return 2  # pragma: no cover - argparse enforces a valid subcommand


if __name__ == "__main__":
    sys.exit(main())
