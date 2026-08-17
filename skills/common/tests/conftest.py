"""Make skill_validator importable from tests.

Unlike the other skills' ``tests/conftest.py`` (which add ``<skill>/scripts`` to
``sys.path`` because their tested module lives under ``scripts/``), the module under
test here — ``skill_validator.py`` — lives directly in this skill's root, alongside
``__init__.py``. So this adds the skill root itself.
"""

from __future__ import annotations

import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)
