"""The matrix completeness guard (F-053) and the coverage-artifact freshness gate.

Asserts, against the live census and the AST cell map from
``tests/_matrix_coverage.py``:

* every registered component has matrix rows meeting its kind's dim floor
  (both directions — an unregistered declaration fails too);
* the alias→canonical pairing per kind equals ``FROZEN_ALIAS_MAP`` exactly;
* every kind appears in at least one M8 pipeline (kinds read from validated
  ``EvalConfig`` fields, never from ``"type"`` string literals);
* waivers and follow-on obligations cannot go stale in either direction;
* designated registry classes contain no all-literal parametrize;
* ``docs/matrix-coverage.md`` matches an in-memory regeneration.

Run ``python tests/test_matrix_coverage.py --update`` to (re)write the artifact and
``--check`` for the freshness gate (exit 1 when stale) — the ``mermaid_gen.py
--check`` contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Script-mode bootstrap: `python tests/test_matrix_coverage.py --update` starts with
# tests/ as sys.path[0] and no conftest handling, so the repo root (and src/, for an
# uninstalled checkout) must be prepended before the `tests.` imports resolve.
if __package__ in (None, ""):
    for _p in (str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent.parent / "src")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

from tests import _matrix_coverage as mc
from tests.test_matrix_eval_tools import PIPELINES

# One census/cell-map per module load; the census itself is lru_cached per process.
CENSUS = mc.registry_census()
CLASSES = mc.extract_matrix_classes(mc.matrix_files())


# ------------------------------------------------------------------ the guard itself


def test_census_is_populated() -> None:
    """Vacuity guard: a probe returning a thin census must fail, not pass silently."""
    assert len(CENSUS) >= 5
    assert len(mc.census_names(CENSUS, "scorer")) >= 14
    assert all(mc.census_names(CENSUS, kind) for kind in CENSUS)


def test_cell_map_is_populated() -> None:
    """Vacuity guard: the extractor finding nothing means the convention broke, not
    that the matrix is empty."""
    assert len(CLASSES) > 20
    total_cells = sum(len(cls.dim_counts) for cls in CLASSES)
    assert total_cells > 100


def test_every_component_meets_its_dim_floor() -> None:
    problems = mc.coverage_problems(CENSUS, CLASSES)
    assert not problems, "matrix coverage policy violations:\n  " + "\n  ".join(problems)


def test_alias_pairings_match_the_frozen_map_exactly() -> None:
    """The directed pairing guarantee. `Registry._aliases` assignment has no duplicate
    guard, so a repointed alias still resolves — only exact equality catches it. A new
    alias fails here until it is added to FROZEN_ALIAS_MAP (and ADR 0032's change
    process); a dropped or repointed one fails immediately."""
    live = {kind: mc.census_aliases(CENSUS, kind) for kind in sorted(CENSUS)}
    assert live == mc.FROZEN_ALIAS_MAP


def test_every_kind_appears_in_at_least_one_m8_pipeline() -> None:
    used = mc.pipeline_kinds(PIPELINES)
    empty = sorted(kind for kind, names in used.items() if not names)
    assert not empty, f"kinds with no M8 pipeline coverage: {empty}"


def test_no_literal_parametrize_in_designated_registry_classes() -> None:
    violations = mc.literal_parametrize_violations(mc.matrix_files())
    assert not violations, "\n".join(violations)


def test_matrix_doc_is_fresh() -> None:
    fresh, _ = mc.doc_is_fresh()
    assert fresh, f"{mc.doc_path()} is stale — regenerate and commit: python tests/test_matrix_coverage.py --update"


# ------------------------------------------------------------- guard self-tests


def _census_with_extra(kind: str, name: str) -> dict[str, dict[str, object]]:
    synthetic: dict[str, dict[str, object]] = {
        k: {"names": list(mc.census_names(CENSUS, k)), "aliases": dict(mc.census_aliases(CENSUS, k))} for k in CENSUS
    }
    synthetic[kind]["names"] = sorted([*mc.census_names(CENSUS, kind), name])
    return synthetic


def test_guard_fails_a_component_with_no_rows() -> None:
    problems = mc.coverage_problems(_census_with_extra("scorer", "zz_new_scorer"), CLASSES)
    assert any("zz_new_scorer" in p and "no matrix rows" in p for p in problems)


def test_guard_fails_an_unknown_census_kind_with_an_actionable_message() -> None:
    synthetic = dict(_census_with_extra("scorer", "zz"))
    synthetic["state_adapter"] = {"names": ["in_memory"], "aliases": {}}
    problems = mc.coverage_problems(synthetic, CLASSES)
    assert any("state_adapter" in p and "REQUIRED_DIMS" in p and "ADR 0032" in p for p in problems)


def test_guard_fails_a_stale_component_declaration() -> None:
    stale = mc.MatrixClass(
        module="test_matrix_x.py",
        name="TestGone",
        kind="scorer",
        components=("no_such_scorer",),
        registry_marker=False,
        dim_counts={1: 1},
    )
    problems = mc.coverage_problems(CENSUS, [*CLASSES, stale])
    assert any("no_such_scorer" in p and "unregistered" in p for p in problems)


def test_guard_fails_an_unmapped_matrix_class() -> None:
    unmapped = mc.MatrixClass(
        module="test_matrix_x.py",
        name="TestMystery",
        kind=None,
        components=(),
        registry_marker=False,
        dim_counts={2: 1},
    )
    problems = mc.coverage_problems(CENSUS, [*CLASSES, unmapped])
    assert any("TestMystery" in p and "no MATRIX_KIND" in p for p in problems)


def test_guard_fails_waivers_in_both_directions(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = {("scorer", "never_registered", 6): "stale"}
    monkeypatch.setattr(mc, "WAIVED", {**mc.WAIVED, **stale})
    problems = mc.coverage_problems(CENSUS, CLASSES)
    assert any("stale waiver" in p and "never_registered" in p for p in problems)

    satisfied = {("scorer", "exact_match", 1): "already has M1 tests"}
    monkeypatch.setattr(mc, "WAIVED", {**mc.WAIVED, **satisfied})
    problems = mc.coverage_problems(CENSUS, CLASSES)
    assert any("waiver no longer needed" in p and "exact_match" in p for p in problems)


def test_guard_fails_a_satisfied_follow_on_row(monkeypatch: pytest.MonkeyPatch) -> None:
    satisfied = mc.FollowOn("some-change", "scorer", "exact_match", "already exists")
    monkeypatch.setattr(mc, "FOLLOW_ON", (*mc.FOLLOW_ON, satisfied))
    problems = mc.coverage_problems(CENSUS, CLASSES)
    assert any("follow-on obligation satisfied" in p and "some-change" in p for p in problems)


def test_extractor_folds_same_file_module_constants(tmp_path: Path) -> None:
    source = (
        'NAMES = ("a", "b")\n'
        "class TestThing:\n"
        '    MATRIX_KIND = "scorer"\n'
        "    MATRIX_COMPONENTS = NAMES\n"
        "    def test_m1_x(self): ...\n"
    )
    path = tmp_path / "test_matrix_synthetic.py"
    path.write_text(source, encoding="utf-8")
    (cls,) = mc.extract_matrix_classes([path])
    assert cls.components == ("a", "b")
    assert cls.dim_counts == {1: 1}


def test_literal_parametrize_detector_fires_on_nested_literals(tmp_path: Path) -> None:
    source = (
        "import pytest\n"
        "class TestFakeRegistry:\n"
        '    @pytest.mark.parametrize("alias,canonical", [("a", "b")])\n'
        "    def test_alias(self, alias, canonical): ...\n"
    )
    path = tmp_path / "test_matrix_synthetic.py"
    path.write_text(source, encoding="utf-8")
    violations = mc.literal_parametrize_violations([path])
    assert violations and "TestFakeRegistry" in violations[0]


class _FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_census_probe_failure_modes_are_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    mc.registry_census.cache_clear()
    try:
        monkeypatch.setattr(mc, "_run_probe", lambda: _FakeCompletedProcess(returncode=3, stderr="boom"))
        with pytest.raises(RuntimeError, match="exit 3"):
            mc.registry_census()

        mc.registry_census.cache_clear()
        monkeypatch.setattr(mc, "_run_probe", lambda: _FakeCompletedProcess(stdout="not json"))
        with pytest.raises(ValueError, match="not valid JSON"):
            mc.registry_census()

        mc.registry_census.cache_clear()

        def _timeout() -> _FakeCompletedProcess:
            raise subprocess.TimeoutExpired(cmd="probe", timeout=1)

        monkeypatch.setattr(mc, "_run_probe", _timeout)
        with pytest.raises(RuntimeError, match="did not finish"):
            mc.registry_census()
    finally:
        mc.registry_census.cache_clear()


def test_census_shape_validation_rejects_malformed_payloads() -> None:
    with pytest.raises(TypeError, match="top level"):
        mc._parse_census([], source="x")
    with pytest.raises(TypeError, match="'names' and 'aliases'"):
        mc._parse_census({"scorer": {"names": []}}, source="x")
    with pytest.raises(ValueError, match="duplicate"):
        mc._parse_census({"scorer": {"names": ["a", "a"], "aliases": {}}}, source="x")


# ----------------------------------------------------------------------- __main__

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="(Re)write docs/matrix-coverage.md")
    group.add_argument("--check", action="store_true", help="Exit 1 if the committed doc is stale")
    args = parser.parse_args()

    if args.update:
        rendered = mc.render_doc()
        mc.doc_path().parent.mkdir(parents=True, exist_ok=True)
        mc.doc_path().write_text(rendered, encoding="utf-8")
        print(f"wrote {mc.doc_path()}")
    else:
        fresh, _ = mc.doc_is_fresh()
        if not fresh:
            print(f"{mc.doc_path()} is stale — regenerate and commit: python tests/test_matrix_coverage.py --update")
            raise SystemExit(1)
        print(f"{mc.doc_path()} is fresh")
