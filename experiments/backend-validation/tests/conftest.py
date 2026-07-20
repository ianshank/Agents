"""Make the experiment package importable when tests run without an editable install.

Mirrors the repo's skill-test conftest pattern (sys.path shim); `make install` remains the
supported path — this only keeps ad-hoc `pytest tests` runs working from the subtree root.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SUBTREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SUBTREE_ROOT not in sys.path:
    sys.path.insert(0, SUBTREE_ROOT)


@pytest.fixture(autouse=True)
def _registry_isolation() -> Iterator[None]:
    """Snapshot/restore the probe registry so test registrations never leak.

    Preflight cross-validates PROBES.yaml ids against the registry in BOTH directions;
    a stray test-registered probe would otherwise fail an unrelated preflight test.
    """
    from backend_validation import registry

    before = dict(registry._PROBE_IMPLS)
    yield
    registry._PROBE_IMPLS.clear()
    registry._PROBE_IMPLS.update(before)


@pytest.fixture()
def tmp_subtree(tmp_path: Path) -> Path:
    """A minimal copy of the subtree (TCB files + schemas + config) for phase tests,
    so tests never write into the real artifacts/ directory."""
    root = tmp_path / "backend-validation"
    root.mkdir()
    source = Path(SUBTREE_ROOT)
    for name in ("PROBES.yaml", "RUBRIC.md", "config.yaml"):
        shutil.copy(source / name, root / name)
    shutil.copytree(source / "schemas", root / "schemas")
    shutil.copytree(source / "deploy", root / "deploy")  # committed TODO-pinned compose files
    return root
