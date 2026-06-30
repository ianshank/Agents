"""Make the bundled ``run`` script importable from tests without installation.

Mirrors the convention used by the other skills' test suites: the skill's
``scripts/`` directory is put on ``sys.path`` so ``import run`` resolves to
``scripts/run.py``.
"""

from __future__ import annotations

import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
