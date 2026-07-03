#!/usr/bin/env python3
"""Select the next feature to implement, respecting the dependency DAG.

Priority ordering (ascending): critical=0 > high=1 > medium=2 > low=3.

Behaviour:
    1. Return any ``in_progress`` feature first (resume).
    2. Among ``todo`` features whose dependencies are all ``done``, pick the
       highest-priority one.
    3. Report blocked features (``todo`` with unmet deps).

Exit codes:
    0 – a feature was selected
    2 – all remaining features are blocked or none remain
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from _cli import configure_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FEATURES_PATH: str = "features.yaml"
PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _load_features(path: Path) -> list[dict[str, Any]]:
    """Load features list from a YAML file."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "features" not in data:
        raise ValueError(f"{path} must contain a top-level 'features' key")
    features = data["features"]
    if not isinstance(features, list):
        raise ValueError(f"{path} 'features' must be a list")
    return features


def _priority_key(feature: dict[str, Any]) -> int:
    """Return a numeric sort key for a feature's priority (lower = higher priority)."""
    return PRIORITY_ORDER.get(feature.get("priority", "low"), 99)


def select_next(features: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the next actionable feature.

    Returns
    -------
    dict or None
        The selected feature, or *None* if all are blocked / complete.
    """
    done_ids: set[str] = {f["id"] for f in features if f.get("status") == "done"}

    # 1. Resume any in_progress feature (highest priority first)
    in_progress = sorted(
        (f for f in features if f.get("status") == "in_progress"),
        key=_priority_key,
    )
    if in_progress:
        selected = in_progress[0]
        logger.info(
            "Resuming in-progress feature: %s – %s",
            selected["id"],
            selected["name"],
        )
        return selected

    # 2. Filter todo features whose deps are all done
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for feat in features:
        if feat.get("status") != "todo":
            continue
        deps: list[str] = feat.get("depends_on", [])
        missing = [d for d in deps if d not in done_ids]
        if missing:
            blocked.append(feat)
            logger.warning(
                "Blocked: %s – %s (waiting on %s)",
                feat["id"],
                feat["name"],
                ", ".join(missing),
            )
        else:
            ready.append(feat)

    if not ready:
        if blocked:
            logger.error(
                "All %d remaining feature(s) are blocked.",
                len(blocked),
            )
        else:
            logger.info("No features remaining – everything is done or deferred.")
        return None

    # Pick highest priority among ready features
    ready.sort(key=_priority_key)
    selected = ready[0]
    logger.info(
        "Next feature: %s – %s (priority=%s)",
        selected["id"],
        selected["name"],
        selected.get("priority", "unknown"),
    )
    return selected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Pick the next feature to implement, respecting the DAG.",
    )
    parser.add_argument(
        "--features",
        default=DEFAULT_FEATURES_PATH,
        help=f"Path to features YAML (default: {DEFAULT_FEATURES_PATH})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry-point: select next feature and print its ID."""
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    features_path = Path(args.features)
    if not features_path.exists():
        logger.error("Features file not found: %s", features_path)
        return 2

    try:
        features = _load_features(features_path)
    except (yaml.YAMLError, ValueError) as exc:
        logger.error("Failed to load features: %s", exc)
        return 2

    selected = select_next(features)
    if selected is None:
        return 2

    # Machine-readable output on stdout
    print(selected["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
