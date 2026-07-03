"""Make the bundled ``adguard`` package importable from tests without installation."""

from __future__ import annotations

import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
