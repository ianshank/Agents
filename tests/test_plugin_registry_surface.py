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

Regenerate after an intentional addition with::

    python tests/test_plugin_registry_surface.py --update

``--update`` itself refuses to rewrite the baseline if doing so would drop or rename a key
-- that would silently rebaseline over the exact breaking change this guard exists to catch.
Pass ``--allow-drops`` only when the drop is deliberate and reviewed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pytest

from tests._registry_probe import run_probe

logger = logging.getLogger(__name__)

_BASELINE_PATH = Path(__file__).parent / "plugin_registry_baseline.json"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_UPDATE_HINT = (
    "--update freezes intentional ADDITIONS only; it does not undo a drop. "
    "A dropped or renamed key must be restored (or kept resolvable via an alias) -- "
    "never rebaseline over a break just to make the guard pass."
)

# Runs in a clean subprocess (see the module docstring). Mirrors tests/conftest.py's own
# sys.path setup (insert(0) for repo root + src, highest precedence) because a bare
# ``python -c`` child gets none of pytest's conftest.py handling: without this, the import
# either fails outright on an uninstalled checkout, or -- worse -- silently resolves to
# whatever ``eval_harness`` happens to already be on sys.path (e.g. a stray editable install
# pointing at an unrelated checkout), which would make this guard measure the wrong code
# without any error at all. ``cwd=_REPO_ROOT`` is set by the caller (_current_surface), so
# Path.cwd() here is exactly the repo root. Registries are discovered dynamically
# (isinstance(obj, Registry) over eval_harness.plugins' module namespace) rather than naming
# them, so a future 6th registry is picked up automatically -- adding one only needs a
# baseline entry, never a code change here. The JSON key is each registry's own ``.kind``
# field (e.g. "scorer"), NOT the module-level variable name lowercased: keying off the
# variable name would make the guard fragile to a purely internal rename (SCORERS ->
# SCORER_REGISTRY) even though the public config-selectable surface never changed.
# ``_aliases`` is read directly because there is no public accessor for the backwards-compat
# alias keys, which are part of the surface.
# The probe is extracted to tests/registry_probe_hook.py to allow mypy/ruff validation.


def _parse_surface(raw: object, *, source: str) -> dict[str, list[str]]:
    """Shape-validate a ``{kind: [key, ...]}`` payload; reject duplicates within a kind.

    Shared by :func:`_current_surface` (subprocess JSON) and :func:`_load_baseline` (the
    committed file), so both a malformed probe output and a hand-edited baseline fail with
    the same clear, source-tagged error instead of a bare ``KeyError``/``AttributeError``.
    Entries must already be strings -- registry keys are a compatibility surface, so a
    non-string entry (e.g. a stray int from a hand-edited baseline) fails loudly rather
    than being silently coerced into a comparable-but-wrong string.
    """
    if not isinstance(raw, dict):
        raise TypeError(f"{source}: top level must be a JSON object")
    shaped: dict[str, list[str]] = {}
    for kind, keys in raw.items():
        if not isinstance(keys, list):
            raise TypeError(f"{source}: {kind!r} must be a list, got {type(keys).__name__}")
        not_str = sorted({type(key).__name__ for key in keys if not isinstance(key, str)})
        if not_str:
            raise TypeError(f"{source}: {kind!r} must be a list of strings, found: {not_str}")
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"{source}: {kind!r} has duplicate key(s): {duplicates}")
        shaped[str(kind)] = list(keys)
    return shaped


def _current_surface() -> dict[str, list[str]]:
    """Return ``{kind: sorted(names + aliases)}`` for the built-in registries only."""
    probe_args = ["tests/registry_probe_hook.py", "--mode", "surface"]
    stdout = run_probe(probe_args)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        # Same debuggability bar as the returncode!=0 branch: a 0-exit-but-garbled-stdout
        # probe (e.g. a stray print from an imported module) must not lose its context.
        raise ValueError(f"registry-surface probe output: not valid JSON ({exc})\nstdout:\n{stdout}") from exc
    surface = _parse_surface(data, source="registry-surface probe output")
    logger.debug("registry surface: %s", {kind: len(keys) for kind, keys in surface.items()})
    return surface


def _load_baseline() -> dict[str, list[str]]:
    """Load and shape-validate the frozen registry surface."""
    with _BASELINE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return _parse_surface(data, source=_BASELINE_PATH.name)


def _surface_diff(frozen: list[str], current: list[str]) -> tuple[list[str], list[str]]:
    """Return ``(dropped, added)``: keys frozen-but-not-current, and current-but-not-frozen.

    Named to match ``tests/test_public_surface.py``'s identically-shaped helper -- the two
    guards tell the same "no undetected breaking change" story and share the pattern name.
    """
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
        dropped, added = _surface_diff(baseline[kind], current[kind])
        if dropped:
            problems.append(f"{kind}: dropped selectable key(s) (breaking): {dropped}")
        if added:
            problems.append(f"{kind}: added key(s) but unfrozen: {added}")
    if problems:
        joined = "\n  ".join(problems)
        raise AssertionError(f"registry surface changed vs baseline:\n  {joined}\n{_UPDATE_HINT}")


def test_surface_diff_detects_drop_and_unfrozen_add() -> None:
    """Self-test the pure diff so the guard's own logic is exercised in both directions."""
    assert _surface_diff(["a", "b"], ["a", "b"]) == ([], [])
    assert _surface_diff(["a", "b"], ["a"]) == (["b"], [])
    assert _surface_diff(["a"], ["a", "b"]) == ([], ["b"])
    assert _surface_diff(["a", "b"], ["b", "c"]) == (["a"], ["c"])


def test_parse_surface_accepts_a_well_shaped_payload() -> None:
    assert _parse_surface({"datasets": ["csv", "jsonl"]}, source="test") == {"datasets": ["csv", "jsonl"]}


def test_parse_surface_rejects_non_dict_top_level() -> None:
    with pytest.raises(TypeError, match="top level must be a JSON object"):
        _parse_surface(["not", "a", "dict"], source="test")


def test_parse_surface_rejects_non_list_value() -> None:
    with pytest.raises(TypeError, match="must be a list"):
        _parse_surface({"datasets": "csv"}, source="test")


def test_parse_surface_rejects_non_string_keys() -> None:
    with pytest.raises(TypeError, match="must be a list of strings"):
        _parse_surface({"datasets": ["csv", 123]}, source="test")


def test_parse_surface_rejects_duplicate_keys_within_a_kind() -> None:
    with pytest.raises(ValueError, match="duplicate key"):
        _parse_surface({"datasets": ["csv", "jsonl", "csv"]}, source="test")


def test_current_surface_raises_on_non_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 0-exit probe that prints non-JSON still fails with a source tag and both streams."""
    import tests.test_plugin_registry_surface

    monkeypatch.setattr(tests.test_plugin_registry_surface, "run_probe", lambda *args, **kwargs: "not json")
    with pytest.raises(ValueError, match="registry-surface probe output"):
        _current_surface()


def _update_baseline(*, allow_drops: bool = False) -> None:
    """Rewrite the baseline JSON from the live built-in registry surface.

    Refuses to silently accept a dropped or renamed key: ``--update`` exists to freeze
    intentional additions (see ``_UPDATE_HINT``), not to rebaseline over a real break. Pass
    ``allow_drops=True`` only for a deliberate, reviewed breaking change. Calls the module's
    other helpers by their bare (global) names -- like the rest of this file, which makes
    them monkeypatchable by the tests below without any extra indirection.
    """
    current = _current_surface()
    if not allow_drops:
        baseline = _load_baseline()
        problems = []
        for kind, frozen in baseline.items():
            dropped, _added = _surface_diff(frozen, current.get(kind, []))
            if dropped:
                problems.append(f"{kind}: {dropped}")
        vanished = sorted(set(baseline) - set(current))
        if vanished:
            problems.append(f"registry kind(s) vanished: {vanished}")
        if problems:
            raise SystemExit(
                "refusing to rewrite the baseline: this would DROP key(s) -- "
                + "; ".join(problems)
                + ". If this is a deliberate, reviewed breaking change, rerun with --allow-drops."
            )
    with _BASELINE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2, sort_keys=True)
        fh.write("\n")
    logger.info("wrote %s", _BASELINE_PATH.name)


def test_update_baseline_refuses_to_silently_drop_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"datasets": ["csv", "jsonl"]}), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_BASELINE_PATH", baseline_path)
    monkeypatch.setattr(sys.modules[__name__], "_current_surface", lambda: {"datasets": ["csv"]})
    with pytest.raises(SystemExit, match="DROP"):
        _update_baseline()
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {"datasets": ["csv", "jsonl"]}


def test_update_baseline_allows_a_drop_with_explicit_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"datasets": ["csv", "jsonl"]}), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_BASELINE_PATH", baseline_path)
    monkeypatch.setattr(sys.modules[__name__], "_current_surface", lambda: {"datasets": ["csv"]})
    _update_baseline(allow_drops=True)
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {"datasets": ["csv"]}


def test_update_baseline_writes_freely_when_there_is_no_drop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({"datasets": ["csv"]}), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_BASELINE_PATH", baseline_path)
    monkeypatch.setattr(sys.modules[__name__], "_current_surface", lambda: {"datasets": ["csv", "jsonl"]})
    _update_baseline()  # an addition-only change must not raise
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {"datasets": ["csv", "jsonl"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plugin-registry surface baseline guard.")
    parser.add_argument("--update", action="store_true", help="Regenerate the baseline JSON")
    parser.add_argument(
        "--allow-drops",
        action="store_true",
        help="Allow --update to remove a key (only for a deliberate, reviewed breaking change)",
    )
    args = parser.parse_args()
    if args.update:
        logging.basicConfig(level=logging.INFO)
        _update_baseline(allow_drops=args.allow_drops)
