"""Self-tests for the matrix completeness guard: proof each check can FAIL.

Split out of ``tests/test_matrix_coverage.py``, which asserts the live matrix meets its
policy floors and doubles as the ``--update``/``--check`` artifact CLI. This module holds
the opposite direction: synthetic censuses, classes and documents constructed so a guard
that had quietly stopped guarding fails HERE. Every check in the sibling module has a
falsification test below — a green guard with no negative control is the exact defect
class the matrix policy exists to prevent (ADR 0032), so the two directions carry equal
weight and only their file changed.

The split was forced by the 500-line ceiling ``scripts/repo_invariant_review.py``
enforces; the seam is the one the file already documented as ``guard self-tests``, so no
test moved between concerns.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from tests import _matrix_coverage as mc

# The live census and cell map, imported rather than recomputed: `registry_census()` is
# lru_cached per process, but `extract_matrix_classes` re-parses every matrix file, and
# these two modules always run in the same session.
from tests.test_matrix_coverage import CENSUS, CLASSES


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
    # A placeholder kind name genuinely absent from REQUIRED_DIMS. `state_adapter` no
    # longer qualifies as of add-stateful-outcome-evaluation (F-060) -- it now has a
    # real policy row (ADR 0032 errata, 2026-08-21) -- so this uses a fictional kind
    # instead, keeping the test's premise (an unknown kind) actually true.
    synthetic = dict(_census_with_extra("scorer", "zz"))
    synthetic["widget_adapter"] = {"names": ["in_memory"], "aliases": {}}
    problems = mc.coverage_problems(synthetic, CLASSES)
    assert any("widget_adapter" in p and "REQUIRED_DIMS" in p and "ADR 0032" in p for p in problems)


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


def test_census_shape_validation_rejects_malformed_payloads() -> None:
    with pytest.raises(TypeError, match="top level"):
        mc._parse_census([], source="x")
    with pytest.raises(TypeError, match="'names' and 'aliases'"):
        mc._parse_census({"scorer": {"names": []}}, source="x")
    with pytest.raises(ValueError, match="duplicate"):
        mc._parse_census({"scorer": {"names": ["a", "a"], "aliases": {}}}, source="x")
    with pytest.raises(TypeError, match="names must be a list of strings"):
        mc._parse_census({"scorer": {"names": [1], "aliases": {}}}, source="x")
    with pytest.raises(TypeError, match="aliases must be a string->string object"):
        mc._parse_census({"scorer": {"names": ["a"], "aliases": {"x": 2}}}, source="x")


def test_census_probe_failure_modes_are_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    mc.registry_census.cache_clear()
    try:
        monkeypatch.setattr(mc, "run_probe", lambda *args, **kwargs: "not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            mc.registry_census()
    finally:
        mc.registry_census.cache_clear()


def test_an_empty_census_never_satisfies_the_floors_vacuously() -> None:
    """ADR 0029's lesson: a check that measured nothing must not report a pass."""
    problems = mc.coverage_problems({}, CLASSES)
    assert problems and "census is empty" in problems[0]


def test_pipeline_vacuous_catches_a_declared_but_uninvoked_component() -> None:
    """The execution-ledger guard must fail a pipeline that names a component it never runs.

    This is the `echo_exact_match` defect in miniature: a pipeline declaring
    `judge: mock` while running no judge-backed scorer. Asserting it here means the
    guard is itself tested, not merely relied upon.
    """
    config = {
        "schema_version": "1.0",
        "run": {"name": "vacuity-probe", "seed": 1},
        "dataset": {"type": "inline", "params": {"items": [{"id": "v1", "inputs": {"q": "x"}}]}},
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "em"}}],
        "judge": {"type": "mock"},
    }
    # Everything ran EXCEPT the judge — the exact shape the ledger reports for a
    # pipeline whose declared judge is never reached by any scorer.
    executed = {
        "vac": {
            "dataset": {"inline"},
            "target": {"echo"},
            "scorer": {"exact_match"},
        }
    }
    vacuous = mc.pipeline_vacuous({"vac": config}, executed)
    assert vacuous == {"vac": {"judge": {"mock"}}}
    assert "declares judge/mock but never invokes it" in mc.format_vacuous(vacuous)


def test_pipeline_vacuous_is_per_pipeline_not_a_repo_wide_union() -> None:
    """A union check would not catch the defect this guard exists for.

    `judge/mock` IS invoked — by the `llm_judge` pipeline. A guard asking "was
    judge/mock executed anywhere in PIPELINES?" answers yes and stays silent about a
    sibling pipeline that only declares it. Pinning the per-pipeline scoping here stops
    a future refactor from quietly widening the diff back into a union.
    """
    declaring_only = {
        "schema_version": "1.0",
        "run": {"name": "declares-only", "seed": 1},
        "dataset": {"type": "inline", "params": {"items": [{"id": "d1", "inputs": {"q": "x"}}]}},
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "exact_match", "params": {"name": "em"}}],
        "judge": {"type": "mock"},
    }
    invoking = {
        "schema_version": "1.0",
        "run": {"name": "invokes", "seed": 1},
        "dataset": {"type": "inline", "params": {"items": [{"id": "i1", "inputs": {"q": "x"}}]}},
        "target": {"type": "echo", "params": {"output_key": "q"}},
        "scorers": [{"type": "llm_judge", "params": {"name": "q"}}],
        "judge": {"type": "mock"},
    }
    executed = {
        "declares_only": {"dataset": {"inline"}, "target": {"echo"}, "scorer": {"exact_match"}},
        "invokes": {
            "dataset": {"inline"},
            "target": {"echo"},
            "scorer": {"llm_judge"},
            "judge": {"mock"},
        },
    }
    vacuous = mc.pipeline_vacuous({"declares_only": declaring_only, "invokes": invoking}, executed)
    # The pipeline that invoked the judge is clean; the one that only declared it is not.
    assert vacuous == {"declares_only": {"judge": {"mock"}}}


def test_probe_refuses_to_run_under_an_instance_level_create_shadow() -> None:
    """A registry shadow makes the ledger under-count silently; probe() must refuse.

    This reproduces the exact residue that defeated the ledger for three commits:
    `monkeypatch.setattr(JUDGES, "create", ...)` reads the *inherited* bound method as the
    old value and, undoing, writes it back as an INSTANCE attribute. `probe()` patches
    `Registry.create` on the class, and an instance attribute wins — so every judge routed
    around the ledger, judge-backed pipelines scored correctly, and the vacuity guard
    reported a judge that had in fact run. A false vacuity finding is worse than none.

    Two assertions, because both halves are load-bearing: that monkeypatch really leaves
    the shadow (so the guard is not defending against an imaginary defect), and that
    `probe()` raises rather than proceeding. `tests/test_budgeted_judge.py` uses
    `mock.patch.object` for this reason and asserts it leaves no shadow.
    """
    from eval_harness.plugins import JUDGES
    from tests._m8_probe import probe

    assert "create" not in vars(JUDGES), "precondition: no pre-existing shadow"
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(JUDGES, "create", lambda *a, **k: None)
        monkeypatch.undo()
        assert "create" in vars(JUDGES), "monkeypatch.setattr on an inherited attr leaves a shadow"
        with pytest.raises(AssertionError, match=r"instance-level 'create' that shadows"), probe():
            pass
    finally:
        vars(JUDGES).pop("create", None)
    assert "create" not in vars(JUDGES), "this test must leave no shadow of its own"


def _synthetic_class(**overrides: object) -> mc.MatrixClass:
    defaults: dict[str, object] = {
        "module": "test_matrix_x.py",
        "name": "TestSynthetic",
        "kind": "scorer",
        "components": ("exact_match",),
        "registry_marker": False,
        "dim_counts": {1: 1},
    }
    defaults.update(overrides)
    return mc.MatrixClass(**defaults)  # type: ignore[arg-type]


def test_guard_refuses_a_matrix_class_that_inherits() -> None:
    """Inherited test_m* methods live in the base's AST, so counting only this class's
    body would under-count cells pytest really runs. Refuse rather than under-count."""
    problems = mc.coverage_problems(CENSUS, [*CLASSES, _synthetic_class(bases=("_Base",))])
    assert any("must not inherit" in p and "_Base" in p for p in problems)


def test_guard_distinguishes_a_bare_string_from_a_missing_declaration() -> None:
    """`MATRIX_COMPONENTS = "exact_match"` is a plausible typo: a bare string is
    iterable, so a naive extractor would silently yield per-character components."""
    typo = _synthetic_class(components=(), components_declared=True)
    problems = mc.coverage_problems(CENSUS, [*CLASSES, typo])
    assert any("not a literal string tuple" in p and "trailing comma" in p for p in problems)

    absent = _synthetic_class(components=(), components_declared=False)
    problems = mc.coverage_problems(CENSUS, [*CLASSES, absent])
    assert any("MATRIX_COMPONENTS is missing" in p for p in problems)


def test_guard_fails_an_unknown_kind_declared_on_a_class() -> None:
    problems = mc.coverage_problems(CENSUS, [*CLASSES, _synthetic_class(kind="not_a_kind")])
    assert any("unknown MATRIX_KIND" in p and "not_a_kind" in p for p in problems)


def test_guard_reports_a_partially_covered_component() -> None:
    """Distinct from 'no rows at all': some dims present, floor not met."""
    thin = {kind: {"names": ["only_one"], "aliases": {}} for kind in CENSUS}
    problems = mc.coverage_problems(thin, [_synthetic_class(components=("only_one",), dim_counts={1: 1})])
    assert any("missing required dim(s)" in p and "'M2'" in p for p in problems)


def test_guard_fails_an_extra_suite_below_its_floor() -> None:
    """gating/engine rows are enforced like kinds — deleting them cannot go unnoticed."""
    problems = mc.coverage_problems(CENSUS, [c for c in CLASSES if c.kind not in mc.EXTRA_SUITES])
    assert any("extra suite" in p and "gating" in p for p in problems)
    assert any("extra suite" in p and "engine" in p for p in problems)


def test_string_tuple_rejects_a_non_string_element() -> None:
    import ast

    assert mc._string_tuple(ast.parse('("a", 2)', mode="eval").body) is None
    assert mc._string_tuple(ast.parse('("a", "b")', mode="eval").body) == ("a", "b")


def test_renderer_marks_a_missing_required_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    """A floor dim with no tests renders as MISSING rather than vanishing — the failure
    mode the derived _GRID_DIMS exists to prevent."""
    monkeypatch.setattr(mc, "extract_matrix_classes", lambda _paths: [])
    monkeypatch.setattr(mc, "WAIVED", {})
    assert "MISSING" in mc.render_doc()


def test_grid_columns_are_derived_from_the_policy() -> None:
    """Adding a dim to any kind's floor must add a rendered column, or a genuinely
    missing cell would render as no cell at all."""
    expected = tuple(sorted(set().union(*mc.REQUIRED_DIMS.values())))
    assert tuple(mc._GRID_DIMS) == expected


def test_table_cells_survive_pipes_and_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    """A `|` fabricates a column and a newline splits the row. Because the freshness gate
    compares rendered-vs-committed, both sides would corrupt identically and stay green
    while the published artifact was wrong — so escaping is the only defence."""
    evil = mc.FollowOn("evil-change", "scorer", None, "note with a | pipe\nand a newline")
    monkeypatch.setattr(mc, "FOLLOW_ON", (evil,))
    rows = [line for line in mc.render_doc().splitlines() if "evil-change" in line]
    assert len(rows) == 1, "the newline must not split the row"
    assert rows[0].count("\\|") == 1, "the content pipe must be escaped"
    assert rows[0].count("|") - rows[0].count("\\|") == 3, "exactly 3 real column delimiters"


def test_freshness_message_shows_the_diff_not_just_the_hint() -> None:
    message = mc.freshness_failure_message("a totally different rendering\n")
    assert mc.REGEN_HINT in message
    assert "---" in message and "+++" in message  # a unified diff, bounded


# --- logging (house convention: name the logger, assert the negative too) -----------


def test_census_and_extraction_log_diagnostics(caplog: pytest.LogCaptureFixture) -> None:
    mc.registry_census.cache_clear()
    try:
        with caplog.at_level(logging.DEBUG, logger="tests._matrix_coverage"):
            mc.registry_census()
            mc.extract_matrix_classes(mc.matrix_files())
    finally:
        mc.registry_census.cache_clear()
    messages = [record.getMessage() for record in caplog.records]
    assert any("census probe:" in m for m in messages), "the interpreter/cwd must be recorded"
    assert any(m.startswith("census: ") for m in messages)
    assert any("cell map:" in m for m in messages)


def test_nothing_is_logged_at_the_default_level(caplog: pytest.LogCaptureFixture) -> None:
    """Diagnostics stay diagnostics: a clean run must be silent at WARNING and above,
    so this logging can never become default-level noise."""
    with caplog.at_level(logging.WARNING, logger="tests._matrix_coverage"):
        mc.coverage_problems(CENSUS, CLASSES)
        mc.extract_matrix_classes(mc.matrix_files())
    assert [r for r in caplog.records if r.name == "tests._matrix_coverage"] == []
