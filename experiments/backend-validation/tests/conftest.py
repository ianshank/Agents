"""Make the experiment package importable when tests run without an editable install.

Mirrors the repo's skill-test conftest pattern (sys.path shim); `make install` remains the
supported path — this only keeps ad-hoc `pytest tests` runs working from the subtree root.
"""

from __future__ import annotations

import os
import sys

SUBTREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUBTREE_ROOT not in sys.path:
    sys.path.insert(0, SUBTREE_ROOT)
