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

import json
import logging
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

#: The committed registry surface, reused so vacuity floors are cross-linked to the
#: surface guard's baseline rather than restating hand-counted numbers.
_BASELINE: dict[str, list[str]] = json.loads(
    (Path(__file__).parent / "plugin_registry_baseline.json").read_text(encoding="utf-8")
)


# ------------------------------------------------------------------ the guard itself


def test_census_is_populated() -> None:
    """Vacuity guard: a probe returning a thin census must fail, not pass silently.

    The kind floor is derived from the policy, not a literal: a hand-written `>= 5`
    silently stops being a floor the moment a sixth registry lands (the queued
    STATE_ADAPTERS), which is exactly the weakening a vacuity guard must not suffer.
    The scorer floor comes from the committed registry baseline, cross-linking this
    guard to the surface guard instead of restating a count.
    """
    assert len(CENSUS) >= len(mc.REQUIRED_DIMS)
    baseline_scorers = {key for key in _BASELINE["scorer"] if key not in mc.FROZEN_ALIAS_MAP["scorer"]}
    assert set(mc.census_names(CENSUS, "scorer")) == baseline_scorers
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


def _matrix_ci_workflow_text() -> str:
    return (Path(__file__).resolve().parent.parent / mc.MATRIX_CI_WORKFLOW).read_text(encoding="utf-8")


def test_every_skip_gated_cell_actually_executes_in_ci() -> None:
    """A cell claimed in the artifact but skipped in CI is a false green — which shipped
    once (parquet gated on pandas, which no extra installs). Now it is a gate."""
    problems = mc.skip_gate_problems(mc.matrix_files(), _matrix_ci_workflow_text())
    assert not problems, "\n".join(problems)


def test_skip_gate_check_catches_an_uninstalled_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact defect that shipped: the class gates on a distribution CI never installs."""
    monkeypatch.setitem(mc.SKIP_GATED_IMPORTS, "TestParquetDataset", "pandas")
    problems = mc.skip_gate_problems(mc.matrix_files(), _matrix_ci_workflow_text())
    assert any("TestParquetDataset" in p and "never verified in CI" in p for p in problems)


def test_skip_gate_check_catches_an_undeclared_gate(tmp_path: Path) -> None:
    source = (
        "import pytest\n"
        "class TestSneaky:\n"
        '    MATRIX_KIND = "scorer"\n'
        '    MATRIX_COMPONENTS = ("contains",)\n'
        "    def setup_class(cls):\n"
        '        pytest.importorskip("nowhere")\n'
        "    def test_m1_x(self): ...\n"
    )
    path = tmp_path / "test_matrix_sneaky.py"
    path.write_text(source, encoding="utf-8")
    problems = mc.skip_gate_problems([path], _matrix_ci_workflow_text())
    assert any("TestSneaky" in p and "absent from SKIP_GATED_IMPORTS" in p for p in problems)


def test_skip_gate_check_catches_a_stale_declaration(tmp_path: Path) -> None:
    """A class that stopped skipping must be removed from the table, or the table rots."""
    path = tmp_path / "test_matrix_empty.py"
    path.write_text("class TestNothing:\n    pass\n", encoding="utf-8")
    problems = mc.skip_gate_problems([path], _matrix_ci_workflow_text())
    assert any("stale skip gate" in p for p in problems)


def test_matrix_doc_is_fresh() -> None:
    """Stale artifact fails, and the failure says HOW it differs, not just that it does."""
    fresh, rendered = mc.doc_is_fresh()
    assert fresh, mc.freshness_failure_message(rendered)


# ----------------------------------------------------------------------- __main__

if __name__ == "__main__":
    import argparse
    import logging

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="(Re)write docs/matrix-coverage.md")
    group.add_argument("--check", action="store_true", help="Exit 1 if the committed doc is stale")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level diagnostics")
    args = parser.parse_args()

    # Without this the guard library's records are discarded at the root default of
    # WARNING, so its census/extraction diagnostics would be invisible in script mode —
    # the G4 defect recorded in NEXT_STEPS (four CLIs logging at INFO with no logging
    # configured). Bare `basicConfig` matches the sibling guard
    # (tests/test_plugin_registry_surface.py); importing scripts/_cli from tests/ would
    # need a third sys.path bootstrap for no gain.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.update:
        # Refuse to launder a hole into a "fresh" artifact: --check compares document
        # text, so writing a doc that faithfully records MISSING cells would make the
        # freshness gate green on a matrix that does not meet its own floors.
        _problems = mc.coverage_problems(mc.registry_census(), mc.extract_matrix_classes(mc.matrix_files()))
        if _problems:
            print(
                "refusing to write the artifact: the matrix does not meet its policy floors.\n  "
                + "\n  ".join(_problems),
                file=sys.stderr,
            )
            raise SystemExit(1)
        rendered = mc.render_doc()
        mc.doc_path().parent.mkdir(parents=True, exist_ok=True)
        mc.doc_path().write_text(rendered, encoding="utf-8")
        print(f"wrote {mc.doc_path()}")
    else:
        fresh, rendered = mc.doc_is_fresh()
        if not fresh:
            # Same message the pytest freshness gate emits, diff included.
            print(mc.freshness_failure_message(rendered), file=sys.stderr)
            raise SystemExit(1)
        print(f"{mc.doc_path()} is fresh")
