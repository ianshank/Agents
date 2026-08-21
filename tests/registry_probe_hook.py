#!/usr/bin/env python3
"""Centralized probe hook script for AST/runtime registry inspection.

Used by test suites (such as tests/_matrix_coverage.py and
tests/test_plugin_registry_surface.py) to extract census and surface data
deterministically via a dedicated subprocess.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval_harness.core.registry import Registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe registry surface/census data.")
    parser.add_argument(
        "--mode",
        choices=["census", "surface"],
        required=True,
        help="Whether to probe census (with aliases) or full surface.",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from eval_harness import plugins

    plugins.load_builtin_plugins()
    registries: dict[str, Registry] = {obj.kind: obj for obj in vars(plugins).values() if isinstance(obj, Registry)}

    if args.mode == "census":
        payload_census: dict[str, Any] = {
            kind: {"names": sorted(reg.names()), "aliases": dict(sorted(reg._aliases.items()))}
            for kind, reg in registries.items()
        }
        print(json.dumps(payload_census))
    else:  # surface
        payload_surface: dict[str, Any] = {
            kind: sorted(set(reg.names()) | set(reg._aliases)) for kind, reg in registries.items()
        }
        print(json.dumps(payload_surface))


if __name__ == "__main__":
    main()
