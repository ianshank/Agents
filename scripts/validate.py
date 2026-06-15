#!/usr/bin/env python3
"""Validate features.yaml structure, DAG integrity, git provenance, and run validation commands.

Supports schema validation (with graceful jsonschema fallback), dependency DAG
cycle/missing-edge detection via DFS coloring (WHITE→GREY→BLACK), git ref
verification, and tier-filtered validation_command execution.

Exit codes:
    0 – all checks passed
    1 – one or more checks failed
    2 – configuration / usage error
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Sequence

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FEATURES_PATH: str = "features.yaml"
DEFAULT_SCHEMA_PATH: str = "features.schema.json"
DEFAULT_TIERS: str = "fast"
PRIORITY_ORDER: Dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DFS colouring for cycle detection
# ---------------------------------------------------------------------------

class _Colour(Enum):
    """DFS node colours for Tarjan-style cycle detection."""
    WHITE = auto()
    GREY = auto()
    BLACK = auto()


def _detect_cycles(
    adj: Dict[str, List[str]],
    all_ids: Set[str],
) -> List[List[str]]:
    """Return a list of cycles found in the DAG via DFS colouring.

    Each cycle is represented as a list of feature IDs forming the loop.
    """
    colour: Dict[str, _Colour] = {fid: _Colour.WHITE for fid in all_ids}
    parent: Dict[str, Optional[str]] = {fid: None for fid in all_ids}
    cycles: List[List[str]] = []

    def _dfs(node: str) -> None:
        colour[node] = _Colour.GREY
        for neighbour in adj.get(node, []):
            if neighbour not in colour:
                # neighbour is not a known feature – skip (caught by missing-edge check)
                continue
            if colour[neighbour] == _Colour.GREY:
                # Back-edge → cycle found – reconstruct
                cycle = [neighbour, node]
                cur = parent[node]
                while cur is not None and cur != neighbour:
                    cycle.append(cur)
                    cur = parent[cur]
                cycle.reverse()
                cycles.append(cycle)
            elif colour[neighbour] == _Colour.WHITE:
                parent[neighbour] = node
                _dfs(neighbour)
        colour[node] = _Colour.BLACK

    for fid in all_ids:
        if colour[fid] == _Colour.WHITE:
            _dfs(fid)
    return cycles


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _load_features(path: Path) -> Dict[str, Any]:
    """Load and return the features YAML document."""
    logger.info("Loading features from %s", path)
    with path.open("r", encoding="utf-8") as fh:
        data: Dict[str, Any] = yaml.safe_load(fh)
    if not isinstance(data, dict) or "features" not in data:
        raise ValueError(f"{path} must be a YAML mapping with a top-level 'features' key")
    return data


def _validate_schema(data: Dict[str, Any], schema_path: Path) -> List[str]:
    """Validate *data* against *schema_path*. Returns list of error messages."""
    errors: List[str] = []
    if not schema_path.exists():
        logger.warning("Schema file %s not found – skipping schema validation", schema_path)
        return errors

    with schema_path.open("r", encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        import jsonschema  # noqa: WPS433 – optional dependency
    except ImportError:
        logger.warning("jsonschema not installed – skipping schema validation")
        return errors

    validator = jsonschema.Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        msg = f"Schema: {err.json_path}: {err.message}"
        errors.append(msg)
        logger.error(msg)
    return errors


def _check_dag(features: List[Dict[str, Any]]) -> List[str]:
    """Check for missing dependency edges and cycles. Returns error messages."""
    errors: List[str] = []
    all_ids: Set[str] = {f["id"] for f in features}
    adj: Dict[str, List[str]] = {}

    for feat in features:
        fid: str = feat["id"]
        deps: List[str] = feat.get("depends_on", [])
        adj[fid] = deps
        for dep in deps:
            if dep not in all_ids:
                msg = f"DAG: {fid} depends on unknown feature {dep}"
                errors.append(msg)
                logger.error(msg)

    cycles = _detect_cycles(adj, all_ids)
    for cycle in cycles:
        msg = f"DAG: cycle detected: {' -> '.join(cycle)}"
        errors.append(msg)
        logger.error(msg)
    return errors


def _check_git_refs(
    features: List[Dict[str, Any]],
    *,
    strict: bool = False,
) -> List[str]:
    """Verify each implemented_in ref resolves to a real commit.

    Parameters
    ----------
    strict:
        When *True*, unresolvable refs are reported as errors.
        When *False* (default), they are warnings only.
    """
    errors: List[str] = []
    for feat in features:
        ref: Optional[str] = feat.get("implemented_in")
        if not ref:
            continue
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            capture_output=True,
        )
        if result.returncode != 0:
            msg = f"Git: {feat['id']} implemented_in ref '{ref}' does not resolve"
            if strict:
                errors.append(msg)
                logger.error(msg)
            else:
                logger.warning(msg)
    return errors


def _run_validation_command(feat: Dict[str, Any]) -> Optional[str]:
    """Run a single feature's validation_command. Return error message or None."""
    fid: str = feat["id"]
    cmd: Optional[str] = feat.get("validation_command")
    if not cmd:
        return f"{fid}: status=done but no validation_command"

    logger.info("Running validation for %s: %s", fid, cmd)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)  # noqa: S602
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
        msg = f"{fid}: validation_command failed ({result.returncode})"
        if tail:
            msg += "\n      " + "\n      ".join(tail)
        return msg
    return None


def _run_validation_commands(
    features: List[Dict[str, Any]],
    *,
    selected_tiers: Set[str],
) -> tuple[List[str], int, int]:
    """Execute validation_command for done, tier-matching features.

    Returns (errors, ran_count, skipped_count).
    """
    errors: List[str] = []
    ran = 0
    skipped = 0
    for feat in features:
        if feat["status"] != "done":
            continue

        tier: str = feat.get("tier", "fast")
        if tier not in selected_tiers:
            logger.debug("Skipping %s (tier=%s not in %s)", feat["id"], tier, selected_tiers)
            skipped += 1
            continue

        err = _run_validation_command(feat)
        ran += 1
        if err:
            errors.append(err)
            logger.error(err)
        else:
            logger.info("Validation: %s passed ✓", feat["id"])
    return errors, ran, skipped


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Validate features.yaml – schema, DAG, git refs, and commands.",
    )
    parser.add_argument(
        "--features",
        default=DEFAULT_FEATURES_PATH,
        help=f"Path to features YAML (default: {DEFAULT_FEATURES_PATH})",
    )
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA_PATH,
        help=f"Path to JSON schema (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--tier",
        default=DEFAULT_TIERS,
        help="Comma-separated tiers to validate (default: fast)",
    )
    parser.add_argument(
        "--strict-git",
        action="store_true",
        help="Treat unresolved implemented_in refs as errors",
    )
    parser.add_argument(
        "--check",
        metavar="F-XXX",
        default=None,
        help="Validate a single feature by ID",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run all validation steps and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    features_path = Path(args.features)
    schema_path = Path(args.schema)
    selected_tiers: Set[str] = {t.strip() for t in args.tier.split(",")}

    if not features_path.exists():
        print(f"Features file not found: {features_path}")
        return 2

    # 1. Load
    try:
        data = _load_features(features_path)
    except (yaml.YAMLError, ValueError) as exc:
        print(f"Failed to load features: {exc}")
        return 2

    features: List[Dict[str, Any]] = data["features"]

    # --check: single feature mode
    if args.check:
        feat = next((f for f in features if f["id"] == args.check), None)
        if not feat:
            print(f"unknown feature {args.check}")
            return 1
        err = _run_validation_command(feat)
        if err:
            print(err)
            return 1
        print(f"{args.check}: OK")
        return 0

    # Collect all errors across phases
    all_errors: List[str] = []

    # 2. Schema
    all_errors.extend(_validate_schema(data, schema_path))

    # 3. DAG
    all_errors.extend(_check_dag(features))

    # 4. Git refs
    all_errors.extend(_check_git_refs(features, strict=args.strict_git))

    # 5. Validation commands
    cmd_errors, ran, skipped = _run_validation_commands(
        features,
        selected_tiers=selected_tiers,
    )
    all_errors.extend(cmd_errors)

    # Summary
    if all_errors:
        print("VALIDATION FAILED:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    done = sum(1 for f in features if f["status"] == "done")
    print(f"OK: {done} done; ran {ran} for tier(s) {sorted(selected_tiers)}, skipped {skipped} (other tiers).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
