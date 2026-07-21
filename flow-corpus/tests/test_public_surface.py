"""Public-API surface guard: every ``__all__`` stays in lockstep with a frozen baseline.

The project advertises a backwards-compatible public surface (``pyproject`` description;
ADR 0009), yet nothing failed CI when an exported name was removed or renamed. This guard
walks each declared package, captures every module that defines ``__all__``, and compares
that live surface to ``public_surface_baseline.json`` with EXACT equality:

* a removed or renamed name  -> breaking change (keep it, or add a deprecated alias);
* an added name or a new ``__all__`` module -> must be frozen (regenerate the baseline).

The baseline is data, not code. Regenerate it after an intended public-API change with::

    python tests/test_public_surface.py --update

This file is byte-identical in every package's ``tests/`` dir and is pinned to the root
copy by ``scripts/check_skill_script_drift.py`` so the copies cannot silently diverge.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

_BASELINE_PATH = Path(__file__).parent / "public_surface_baseline.json"
_UPDATE_HINT = "a drop is breaking; rerun with --update to refreeze intended additions"


def _discover_surface(packages: list[str]) -> dict[str, list[str]]:
    """Return ``{module: sorted(__all__)}`` for every module under *packages* that has one."""
    surface: dict[str, list[str]] = {}
    for top in packages:
        pkg = importlib.import_module(top)
        module_names = [top]
        for info in pkgutil.walk_packages(getattr(pkg, "__path__", []), prefix=f"{top}."):
            module_names.append(info.name)
        for name in module_names:
            exported = getattr(importlib.import_module(name), "__all__", None)
            if exported is not None:
                surface[name] = sorted({str(entry) for entry in exported})
                logger.debug("public surface %s: %d name(s)", name, len(surface[name]))
    return surface


def _load_baseline() -> tuple[list[str], dict[str, list[str]]]:
    """Load and shape-validate the frozen baseline (declared packages + per-module surface)."""
    with _BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise TypeError(f"{_BASELINE_PATH.name}: top level must be a JSON object")
    packages = data.get("packages")
    surface = data.get("surface")
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        raise TypeError(f"{_BASELINE_PATH.name}: 'packages' must be a list of strings")
    if not isinstance(surface, dict):
        raise TypeError(f"{_BASELINE_PATH.name}: 'surface' must be an object")
    shaped: dict[str, list[str]] = {}
    for module_name, exported in surface.items():
        if not isinstance(exported, list):
            raise TypeError(f"{_BASELINE_PATH.name}: surface[{module_name!r}] must be a list")
        shaped[str(module_name)] = [str(entry) for entry in exported]
    return [str(p) for p in packages], shaped


def _surface_diff(frozen: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(dropped, added)``: names frozen-but-not-current, and current-but-not-frozen."""
    frozen_set, current_set = set(frozen), set(current)
    return sorted(frozen_set - current_set), sorted(current_set - frozen_set)


def test_baseline_is_populated() -> None:
    """A truncated or empty baseline must fail loudly, never pass vacuously."""
    packages, surface = _load_baseline()
    assert packages, f"{_BASELINE_PATH.name}: 'packages' is empty"
    assert surface, f"{_BASELINE_PATH.name}: 'surface' is empty"


def test_public_surface_matches_baseline_exactly() -> None:
    """The live public surface must equal the frozen baseline exactly (ADR 0009 contract)."""
    packages, baseline = _load_baseline()
    current = _discover_surface(packages)
    problems: list[str] = []
    gone = sorted(set(baseline) - set(current))
    if gone:
        problems.append(f"module(s) no longer expose __all__ (surface vanished): {gone}")
    new = sorted(set(current) - set(baseline))
    if new:
        problems.append(f"new module(s) expose __all__ but are not frozen: {new}")
    for module_name in sorted(set(baseline) & set(current)):
        dropped, added = _surface_diff(baseline[module_name], current[module_name])
        if dropped:
            problems.append(f"{module_name}.__all__ dropped (breaking): {dropped}")
        if added:
            problems.append(f"{module_name}.__all__ added but unfrozen: {added}")
    if problems:
        joined = "\n  ".join(problems)
        raise AssertionError(f"public surface changed vs baseline:\n  {joined}\n{_UPDATE_HINT}")


def test_public_names_are_unique_and_resolvable() -> None:
    """Every frozen name is listed once in ``__all__`` and still exists on its module."""
    _, baseline = _load_baseline()
    problems: list[str] = []
    for module_name, frozen in baseline.items():
        module = importlib.import_module(module_name)
        exported = list(getattr(module, "__all__", []))
        duplicates = sorted({n for n in exported if exported.count(n) > 1})
        if duplicates:
            problems.append(f"{module_name}.__all__ has duplicate name(s): {duplicates}")
        missing = sorted(n for n in frozen if not hasattr(module, n))
        if missing:
            problems.append(f"{module_name}.__all__ lists name(s) not on the module: {missing}")
    if problems:
        raise AssertionError("invalid __all__ entries:\n  " + "\n  ".join(problems))


def test_surface_diff_detects_drop_and_unfrozen_add() -> None:
    """Self-test the pure diff so the guard's own logic is exercised in both directions."""
    assert _surface_diff(["a", "b"], ["a", "b"]) == ([], [])
    assert _surface_diff(["a", "b"], ["a"]) == (["b"], [])
    assert _surface_diff(["a"], ["a", "b"]) == ([], ["b"])
    assert _surface_diff(["a", "b"], ["b", "c"]) == (["a"], ["c"])


def _update_baseline() -> None:
    """Rewrite the baseline JSON from the live surface of its declared packages."""
    packages, _ = _load_baseline()
    surface = _discover_surface(packages)
    with _BASELINE_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"packages": packages, "surface": surface}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    logger.info("wrote %s (%d module(s) frozen)", _BASELINE_PATH.name, len(surface))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Public-API surface baseline guard.")
    parser.add_argument("--update", action="store_true", help="Regenerate the baseline JSON")
    if parser.parse_args().update:
        logging.basicConfig(level=logging.INFO)
        _update_baseline()
