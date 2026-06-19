#!/usr/bin/env python3
"""Architecture drift gate (deterministic — no model in the decision path).

    python scripts/drift_check.py --manifest architecture.yaml
    python scripts/drift_check.py --manifest architecture.yaml --emit-actual

Extracts the real import graph with grimp, folds it to components, and diffs
against the manifest's declared edges. An undocumented component edge is drift =>
exit 1. ``--emit-actual`` instead prints a ``dependencies:`` block from the real
graph (for bootstrapping a manifest) and exits 0.

This is the blocking gate: same inputs always yield the same exit code.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adguard import (
    AdGuardError,
    configure_logging,
    diff_edges,
    emit_dependencies_block,
    extract_graph,
    fold_to_components,
    format_report,
    get_logger,
    load_manifest,
)

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Check the import graph against the architecture manifest.")
    ap.add_argument(
        "--manifest",
        default=os.environ.get("ADGUARD_MANIFEST", "architecture.yaml"),
        help="path to architecture.yaml (default: $ADGUARD_MANIFEST or architecture.yaml)",
    )
    ap.add_argument(
        "--emit-actual",
        action="store_true",
        help="print a dependencies: block from the real graph and exit 0 (bootstrap)",
    )
    ap.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="KEY.PATH=VALUE",
        help="override a manifest value (repeatable)",
    )
    ap.add_argument(
        "--log-level",
        default=os.environ.get("ADGUARD_LOG_LEVEL", "INFO"),
        help="logging level (default: $ADGUARD_LOG_LEVEL or INFO)",
    )
    return ap


def _prepend_sys_path(dirs: Sequence[str]) -> None:
    """Make the analysed roots importable by grimp without hardcoding paths."""
    for raw in dirs:
        resolved = os.path.abspath(raw)
        if resolved not in sys.path:
            sys.path.insert(0, resolved)
            logger.debug("prepended sys.path entry: %s", resolved)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(level=args.log_level)

    try:
        manifest = load_manifest(args.manifest, overrides=args.overrides)
        _prepend_sys_path(manifest.sys_path)
        module_graph = extract_graph(manifest.root_packages)
        actual = fold_to_components(module_graph, manifest.components)
    except AdGuardError as exc:
        logger.error("drift check failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.emit_actual:
        # Bootstrap mode: print the real edges for human review. No gate.
        sys.stdout.write(emit_dependencies_block(actual))
        return 0

    diff = diff_edges(actual, manifest.dependencies)
    report = format_report(diff)
    if diff.has_drift:
        print(report, file=sys.stderr)
        logger.error("architecture drift detected: %d undocumented edge(s)", len(diff.undocumented))
        return 1

    print(report)
    if diff.unused:
        logger.warning("%d declared edge(s) not observed in code", len(diff.unused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
