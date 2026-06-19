from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
# SRC and ROOT keep their original (highest) precedence; insert(0) prepends, so the
# package layout resolves first. scripts/ is appended at the lowest precedence — it
# only holds standalone tooling modules and must never shadow real packages.
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))

from eval_harness.plugins import bootstrap  # noqa: E402

bootstrap()
