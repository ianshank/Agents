"""Plugin-registry surface guard: registered config keys are frozen (compat contract).

Users select components by string in their config (``type: openai``, ``scorer: weighted``,
target ``type: llm``), and aliases keep configs written against an earlier version working
(``csv_file`` -> ``csv``, ``claude`` -> ``anthropic``). Those keys are a public,
backwards-compatible surface that ``__all__`` does NOT capture: removing or renaming one
silently breaks every config that used it. This guard freezes the built-in registry surface
in ``plugin_registry_baseline.json`` and requires EXACT equality:

* a removed or renamed key -> breaking change (keep it, or add an alias);
* a new key -> must be frozen (regenerate the baseline in the same change).

The surface is read in a FRESH interpreter on purpose: the registries are process-global and
some tests register doubles into them (``tests/test_composite_scorer.py``,
``tests/test_langfuse_prompts.py``), so an in-process read would be order-dependent — only a
clean subprocess sees exactly the built-in surface.

Regenerate after an intended change with::

    python tests/test_plugin_registry_surface.py --update
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

_BASELINE_PATH = Path(__file__).parent / "plugin_registry_baseline.json"
_UPDATE_HINT = (
    "--update freezes intentional ADDITIONS only; it does not undo a drop. "
    "A dropped or renamed key must be restored (or kept resolvable via an alias) -- "
    "never rebaseline over a break just to make the guard pass."
)

# Runs in a clean subprocess (see the module docstring). ``_aliases`` is read directly because
# there is no public accessor for the backwards-compat alias keys, which are part of the surface.
_PROBE = """\
import json

from eval_harness.plugins import DATASETS, JUDGES, SCORERS, SINKS, TARGETS, load_builtin_plugins

load_builtin_plugins()
registries = {
    "datasets": DATASETS,
    "judges": JUDGES,
    "scorers": SCORERS,
    "sinks": SINKS,
    "targets": TARGETS,
}
surface = {kind: sorted(set(reg.names()) | set(reg._aliases)) for kind, reg in registries.items()}
print(json.dumps(surface))
"""


def _parse_surface(raw: object, *, source: str) -> dict[str, list[str]]:
    """Shape-validate a ``{kind: [key, ...]}`` payload; reject duplicates within a kind.

    Shared by :func:`_current_surface` (subprocess JSON) and :func:`_load_baseline` (the
    committed file), so both a malformed probe output and a hand-edited baseline fail with
    the same clear, source-tagged error instead of a bare ``KeyError``/``AttributeError``.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"{source}: top level must be a JSON object")
    shaped: dict[str, list[str]] = {}
    for kind, keys in raw.items():
        if not isinstance(keys, list):
            raise TypeError(f"{source}: {kind!r} must be a list, got {type(keys).__name__}")
        names = [str(key) for key in keys]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"{source}: {kind!r} has duplicate key(s): {duplicates}")
        shaped[str(kind)] = names
    return shaped


def _current_surface() -> dict[str, list[str]]:
    """Return ``{kind: sorted(names + aliases)}`` for the built-in registries only."""
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        # Surface the child's traceback instead of an opaque CalledProcessError, so a probe
        # failure in CI is debuggable (e.g. an import error in eval_harness).
        raise RuntimeError(
            f"registry-surface probe failed (exit {completed.returncode})\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    surface = _parse_surface(json.loads(completed.stdout), source="registry-surface probe output")
    logger.debug("registry surface: %s", {kind: len(keys) for kind, keys in surface.items()})
    return surface


def _load_baseline() -> dict[str, list[str]]:
    """Load and shape-validate the frozen registry surface."""
    with _BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return _parse_surface(data, source=_BASELINE_PATH.name)


def _diff(frozen: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(dropped, added)``: keys frozen-but-not-current, and current-but-not-frozen."""
    frozen_set, current_set = set(frozen), set(current)
    return sorted(frozen_set - current_set), sorted(current_set - frozen_set)


def test_registry_baseline_is_populated() -> None:
    """A truncated or empty baseline must fail loudly, never pass vacuously."""
    baseline = _load_baseline()
    assert baseline, f"{_BASELINE_PATH.name} is empty"
    for kind, keys in baseline.items():
        assert keys, f"{_BASELINE_PATH.name}: {kind!r} froze no keys"


def test_registry_surface_matches_baseline_exactly() -> None:
    """The built-in registry surface must equal the frozen baseline (compat contract)."""
    baseline = _load_baseline()
    current = _current_surface()
    problems: list[str] = []
    gone = sorted(set(baseline) - set(current))
    if gone:
        problems.append(f"registry kind(s) vanished: {gone}")
    new = sorted(set(current) - set(baseline))
    if new:
        problems.append(f"new registry kind(s) not frozen: {new}")
    for kind in sorted(set(baseline) & set(current)):
        dropped, added = _diff(baseline[kind], current[kind])
        if dropped:
            problems.append(f"{kind}: dropped selectable key(s) (breaking): {dropped}")
        if added:
            problems.append(f"{kind}: added key(s) but unfrozen: {added}")
    if problems:
        joined = "\n  ".join(problems)
        raise AssertionError(f"registry surface changed vs baseline:\n  {joined}\n{_UPDATE_HINT}")


def test_diff_detects_drop_and_unfrozen_add() -> None:
    """Self-test the pure diff so the guard's own logic is exercised in both directions."""
    assert _diff(["a", "b"], ["a", "b"]) == ([], [])
    assert _diff(["a", "b"], ["a"]) == (["b"], [])
    assert _diff(["a"], ["a", "b"]) == ([], ["b"])
    assert _diff(["a", "b"], ["b", "c"]) == (["a"], ["c"])


def test_parse_surface_accepts_a_well_shaped_payload() -> None:
    assert _parse_surface({"datasets": ["csv", "jsonl"]}, source="test") == {"datasets": ["csv", "jsonl"]}


def test_parse_surface_rejects_non_dict_top_level() -> None:
    with pytest.raises(TypeError, match="top level must be a JSON object"):
        _parse_surface(["not", "a", "dict"], source="test")


def test_parse_surface_rejects_non_list_value() -> None:
    with pytest.raises(TypeError, match="must be a list"):
        _parse_surface({"datasets": "csv"}, source="test")


def test_parse_surface_rejects_duplicate_keys_within_a_kind() -> None:
    with pytest.raises(ValueError, match="duplicate key"):
        _parse_surface({"datasets": ["csv", "jsonl", "csv"]}, source="test")


def _update_baseline() -> None:
    """Rewrite the baseline JSON from the live built-in registry surface."""
    with _BASELINE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(_current_surface(), fh, indent=2, sort_keys=True)
        fh.write("\n")
    logger.info("wrote %s", _BASELINE_PATH.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plugin-registry surface baseline guard.")
    parser.add_argument("--update", action="store_true", help="Regenerate the baseline JSON")
    if parser.parse_args().update:
        logging.basicConfig(level=logging.INFO)
        _update_baseline()
