from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
# SRC, ROOT, and SCRIPTS are appended to sys.path if not present. Appending (rather than
# prepending) ensures we do not shadow any installed packages during testing.
for _p in (str(ROOT), str(SRC)):
    if _p not in sys.path:
        sys.path.append(_p)
if str(SCRIPTS) not in sys.path:
    sys.path.append(str(SCRIPTS))

from eval_harness.plugins import bootstrap  # noqa: E402

bootstrap()
