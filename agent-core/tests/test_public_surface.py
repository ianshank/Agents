"""Public-API surface guard: ``__all__`` is append-only (backwards-compat contract).

The project advertises a backwards-compatible public surface, but nothing failed
CI when an exported name was removed or renamed. This guard freezes each package's
public ``__all__`` (captured in ``public_surface_baseline.json``) and fails if a
frozen name later disappears. Additions stay free; a removal or rename must be a
deliberate, reviewed break that drops the name from the baseline in the same change
(and, for a rename, keeps a deprecated alias per ADR 0009's compatibility surface).

The baseline is data, not code, so regenerating it to ADD names is a trivial,
reviewable diff.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

_BASELINE_PATH = Path(__file__).parent / "public_surface_baseline.json"


def _load_baseline() -> dict[str, list[str]]:
    with _BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict), "baseline must be a {module: [names]} object"
    return {str(module): [str(name) for name in names] for module, names in data.items()}


def test_public_surface_is_append_only() -> None:
    """No frozen public name may be removed or renamed (that is a breaking change)."""
    for module_name, frozen in _load_baseline().items():
        module = importlib.import_module(module_name)
        current = set(getattr(module, "__all__", []))
        dropped = sorted(set(frozen) - current)
        assert not dropped, f"{module_name}.__all__ dropped public name(s): {dropped}"


def test_public_names_are_unique_and_resolvable() -> None:
    """Every exported name is listed once and actually exists on the module."""
    for module_name in _load_baseline():
        module = importlib.import_module(module_name)
        names = list(getattr(module, "__all__", []))
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert not duplicates, f"{module_name}.__all__ has duplicate name(s): {duplicates}"
        unresolved = sorted(name for name in names if not hasattr(module, name))
        assert not unresolved, f"{module_name}.__all__ lists name(s) not on module: {unresolved}"
