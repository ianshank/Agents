#!/usr/bin/env python3
"""Generate (or freshness-check) the Mermaid C4 Component diagram.

    python scripts/mermaid_gen.py --manifest architecture.yaml -o architecture.mmd
    python scripts/mermaid_gen.py --manifest architecture.yaml --check -o architecture.mmd

Without ``--check`` it writes the diagram derived from the manifest. With
``--check`` it regenerates in memory and compares (after normalisation) against
the committed file, exiting 1 if they differ — this is the freshness gate that
keeps the committed diagram from rotting. Deterministic by construction.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adguard import (
    AdGuardError,
    configure_logging,
    get_logger,
    load_manifest,
    render_mermaid,
)
from adguard.mermaid import normalize_text

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Generate or check the Mermaid C4 component diagram.")
    ap.add_argument(
        "--manifest",
        default=os.environ.get("ADGUARD_MANIFEST", "architecture.yaml"),
        help="path to architecture.yaml (default: $ADGUARD_MANIFEST or architecture.yaml)",
    )
    ap.add_argument(
        "-o",
        "--out",
        default=None,
        help="output path (default: manifest output.mermaid_path)",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="compare regenerated diagram to the committed file; exit 1 on drift",
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(level=args.log_level)

    try:
        manifest = load_manifest(args.manifest, overrides=args.overrides)
    except AdGuardError as exc:
        logger.error("manifest load failed: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_path = args.out or manifest.mermaid_path()
    rendered = render_mermaid(manifest)

    if args.check:
        committed_file = Path(out_path)
        if not committed_file.is_file():
            print(
                f"error: committed diagram {out_path!r} is missing; run mermaid_gen.py to create it",
                file=sys.stderr,
            )
            return 1
        committed = normalize_text(committed_file.read_text(encoding="utf-8"))
        if committed != rendered:
            print(
                f"error: {out_path} is stale — regenerate it from {args.manifest} and commit.",
                file=sys.stderr,
            )
            logger.error("freshness check failed for %s", out_path)
            return 1
        print(f"{out_path} is up to date.")
        return 0

    Path(out_path).write_text(rendered, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
