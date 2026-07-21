"""Make the bundled ``deploygen`` package and ``gen_deploy`` runner importable from tests."""

from __future__ import annotations

import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
