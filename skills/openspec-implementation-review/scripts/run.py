#!/usr/bin/env python3
"""CLI entrypoint for the openspec-implementation-review skill.

  python scripts/run.py locate   --change <id>
  python scripts/run.py detect
  python scripts/run.py plan     --change <id> [--out-dir DIR]
  python scripts/run.py compose  --change <id> --body-file <reviewer-output.md>
  python scripts/run.py validate --change <id>

See implreview/cli.py for the full argument reference; this file only wires it up so the skill
matches every other full-package skill's ``scripts/run.py`` / ``scripts/<pkg>/`` shape.

Exit codes: 0 success; 1 found-but-not-ready or found-but-invalid; 2 usage / not-found.
"""

from __future__ import annotations

import sys

from implreview.cli import main

if __name__ == "__main__":
    sys.exit(main())
