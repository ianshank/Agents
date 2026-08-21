#!/usr/bin/env python3
"""Check READMEs against component registries (delegating to extract_registries)."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts directory is importable
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import extract_registries  # noqa: E402


def main() -> None:
    code = extract_registries.main(["--check"])
    if code != 0:
        sys.exit(code)


if __name__ == "__main__":
    main()
