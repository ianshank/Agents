#!/usr/bin/env python3
"""Tests for the test-generation corpus and its generator.

The corpus is committed, so most of what matters is a property of the *artifact*: it
regenerates byte-identically, its equivalence marks are true, and its obligations are
reachable. Those are checked against the committed files rather than against a rebuilt
copy, because a generator that agrees with itself proves nothing about what shipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_testgen_corpus as gen
import pytest

# The domain logic lives in the split-out library; the CLI module keeps assembly and I/O.
import _testgen_corpus_lib as lib  # isort: skip

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "corpora" / "testgen" / "v1"


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads((CORPUS / "items.json").read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return loaded


class TestCommittedCorpus:
    def test_the_committed_corpus_regenerates_byte_identically(self) -> None:
        """The freshness guard, run against what is actually committed."""
        assert gen.check_corpus(CORPUS) == []

    def test_the_manifest_hash_matches_every_item(self, items: list[dict], manifest: dict) -> None:
        """A hand-edited item fails here even if it stays valid JSON."""
        assert manifest["item_count"] == len(items)
        for item in items:
            assert manifest["items"][item["id"]] == gen._item_hash(item), item["id"]

    def test_every_stratum_is_represented(self, manifest: dict) -> None:
        assert set(manifest["strata"]) == set(lib._TEMPLATES)
        assert all(count == gen.ITEMS_PER_STRATUM for count in manifest["strata"].values())

    def test_a_holdout_split_exists_and_is_a_minority(self, manifest: dict) -> None:
        holdout = manifest["splits"].get("holdout", 0)
        assert 0 < holdout < manifest["item_count"] * 0.5

    def test_no_item_ships_a_dead_loop_body(self, items: list[dict]) -> None:
        """`range(0)` makes a loop body unreachable, so no mutation in it can be killed.

        The item would still validate and still ship — it would simply teach nothing about
        the stratum it claims to represent. Found by reading a generated item, which is why
        the corpus is committed and reviewable rather than built on the fly.
        """
        assert not [item["id"] for item in items if "range(0)" in item["reference"]]

    def test_every_item_can_discriminate(self, items: list[dict]) -> None:
        """An item with no non-equivalent mutant or no obligation measures nothing."""
        for item in items:
            assert [m for m in item["mutants"] if not m["equivalent"]], item["id"]
            assert item["obligations"], item["id"]

    def test_every_obligation_witness_is_a_real_non_equivalent_mutant(self, items: list[dict]) -> None:
        """An obligation whose witness is equivalent could never be shown covered."""
        for item in items:
            live = {m["id"] for m in item["mutants"] if not m["equivalent"]}
            for obligation in item["obligations"]:
                assert obligation["witness_mutant"] in live, (item["id"], obligation["id"])

    def test_equivalence_marks_are_true_on_the_grid(self, items: list[dict]) -> None:
        """Re-derived from the sources, not trusted: the mark drives every denominator."""
        for item in items:
            reference = lib._behaviour(item["reference"], item["focal_name"])
            for mutant in item["mutants"]:
                behaviour = lib._behaviour(mutant["source"], item["focal_name"])
                assert (behaviour == reference) is mutant["equivalent"], (item["id"], mutant["id"])

    def test_differs_at_indices_match_the_recomputed_behaviour(self, items: list[dict]) -> None:
        """`differs_at` is what makes "covered" a measurement, so it is checked too."""
        for item in items[:12]:  # a stratum's worth; the full sweep is the test above
            reference = lib._behaviour(item["reference"], item["focal_name"])
            for mutant in item["mutants"]:
                behaviour = lib._behaviour(mutant["source"], item["focal_name"])
                expected = [i for i, (a, b) in enumerate(zip(reference, behaviour, strict=True)) if a != b]
                assert mutant["differs_at"] == expected, (item["id"], mutant["id"])


class TestReferenceSuites:
    def test_every_item_ships_every_suite_kind(self, items: list[dict]) -> None:
        for item in items:
            assert set(item["suites"]) == set(lib.SUITE_KINDS), item["id"]

    def test_the_thorough_suite_distinguishes_every_non_equivalent_mutant(self, items: list[dict]) -> None:
        """The known-good reference must actually be good, or the corpus has no ceiling."""
        for item in items:
            covering = set(lib._covering_indices(_mutant_records(item)))
            for mutant in item["mutants"]:
                if mutant["equivalent"]:
                    continue
                assert covering & set(mutant["differs_at"]), (item["id"], mutant["id"])

    def test_the_thorough_suite_is_small_not_exhaustive(self, items: list[dict], manifest: dict) -> None:
        """A suite asserting all 91 grid points is enumeration, not coverage.

        Shipping one as the known-good reference would make the corpus reward exhaustive
        input enumeration over behavioural coverage — and quadrupled the committed size.
        """
        grid_size = manifest["grid_size"]
        for item in items:
            assertions = item["suites"]["thorough"].count("assert ")
            assert assertions < grid_size / 2, (item["id"], assertions)

    def test_the_broken_suite_fails_at_import(self, items: list[dict]) -> None:
        """Compiled, not grepped. `assert "raise" in source` is satisfied by a comment."""
        for item in items:
            source = item["suites"]["broken"]
            module: dict[str, Any] = {}
            with pytest.raises(BaseException):  # noqa: B017 - any import-time failure is the property
                exec(compile(source, f"<broken:{item['id']}>", "exec"), module)

    def test_the_false_alarm_suite_extends_the_thorough_one(self, items: list[dict]) -> None:
        """It must differ from `thorough` ONLY by the false alarm, or it confounds two axes."""
        for item in items:
            assert item["suites"]["false_alarm"].startswith(item["suites"]["thorough"])
            assert "test_false_alarm" in item["suites"]["false_alarm"]


class TestCalibration:
    """The four suites are only useful if their scores are actually known.

    Everything in ``TestReferenceSuites`` is a property of the suite *text* — set
    membership, a substring, a count of ``assert ``. None of it executes anything, so the
    corpus's entire stated purpose ("10 known-good and 10 known-bad", so four scorers with
    no published dynamic range become calibratable) rested on nothing an automated check
    could see. A generator change that quietly made ``thorough`` score 0.4 would have
    passed every test in this file.

    Deliberately one representative item, chosen as the one with the fewest mutants:
    each suite kind costs one reference subprocess plus one per mutant, and the properties
    below are about the *generator*, which produces all sixty items the same way.
    """

    @staticmethod
    def _cheapest(items: list[dict]) -> dict[str, Any]:
        return min(items, key=lambda item: (len([m for m in item["mutants"] if not m["equivalent"]]), item["id"]))

    @staticmethod
    def _run(item: dict[str, Any], kind: str) -> dict[str, Any]:
        from eval_harness.targets.testgen import EVIDENCE_KEY, run_generated_suite

        result = run_generated_suite(
            {
                "focal_name": item["focal_name"],
                "reference": item["reference"],
                "suite": item["suites"][kind],
                "mutants": item["mutants"],
                "obligations": item["obligations"],
                "grid": [list(point) for point in lib.GRID],
            }
        )
        evidence: dict[str, Any] = result.metadata[EVIDENCE_KEY]
        return evidence

    def test_the_thorough_suite_is_the_corpus_ceiling(self, items: list[dict]) -> None:
        """Executable, green on correct code, kills every non-equivalent mutant."""
        item = self._cheapest(items)
        evidence = self._run(item, "thorough")
        assert evidence["collection_error"] is None
        assert evidence["collected"] > 0
        assert evidence["green_on_correct"]["failed"] == 0, "the known-GOOD suite must be green on correct code"
        assert evidence["mutants"]["killed"] == evidence["mutants"]["generated"], item["id"]
        assert set(evidence["obligations_covered"]) == set(evidence["obligations_declared"])

    def test_the_weak_suite_scores_strictly_below_the_thorough_one(self, items: list[dict]) -> None:
        """Two known-good/known-bad points that a single blended score would collapse.

        REGRESSION. `weak` used to assert the first element of the greedy set cover — the
        single point separating the MOST mutants — so the known-BAD fixture was built from
        the strongest assertion available. For 32 of these 60 items it came out identical
        to `thorough` apart from the test function's name, and this assertion, the first to
        actually RUN either suite, is what surfaced it.
        """
        item = self._cheapest(items)
        thorough, weak = self._run(item, "thorough"), self._run(item, "weak")
        assert weak["collected"] > 0, "weak is bad, not broken -- the distinction is the point"
        assert weak["mutants"]["killed"] < thorough["mutants"]["killed"], item["id"]
        assert len(weak["obligations_covered"]) <= len(thorough["obligations_covered"])

    def test_the_manifest_reports_the_corpus_dynamic_range_honestly(self, items: list[dict], manifest: dict) -> None:
        """`weak_strictly_weaker_items` is a measurement, and it must match the artifact.

        The claim it replaces was prose: "10 known-good and 10 known-bad". Half the corpus
        did not meet it, and no check could see that because the number was never written
        down. Recomputed here from what SHIPPED rather than from a fresh generation, so a
        hand-edited manifest fails.
        """
        recomputed = sum(1 for item in items if lib.weak_is_strictly_weaker(item))
        assert manifest["weak_strictly_weaker_items"] == recomputed
        assert recomputed == len(items), (
            "every item's known-bad suite must be strictly weaker than its known-good one; "
            f"{len(items) - recomputed} item(s) cannot calibrate the mutation axis"
        )

    def test_the_false_alarm_suite_moves_only_the_false_alarm_axis(self, items: list[dict]) -> None:
        """The separation requirement, asserted by execution rather than by construction.

        A suite that is red on correct code must not thereby look better at finding faults
        -- the exact confound `killed` is defined to exclude.
        """
        item = self._cheapest(items)
        thorough, false_alarm = self._run(item, "thorough"), self._run(item, "false_alarm")
        assert false_alarm["green_on_correct"]["failed"] > 0, "it must actually raise a false alarm"
        assert false_alarm["mutants"]["killed"] <= thorough["mutants"]["killed"], item["id"]

    def test_the_broken_suite_is_not_executable(self, items: list[dict]) -> None:
        """`test_executability` is the gate the other three depend on; this is its fixture."""
        evidence = self._run(self._cheapest(items), "broken")
        assert evidence["collection_error"] is not None
        assert evidence["collected"] == 0


class TestEvalDatasets:
    def test_one_dataset_ships_per_suite_kind(self, items: list[dict]) -> None:
        for kind in lib.SUITE_KINDS:
            path = CORPUS / "eval" / f"{kind}.jsonl"
            assert path.exists(), kind
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            assert len(records) == len(items)

    def test_records_carry_everything_the_target_needs(self) -> None:
        record = json.loads((CORPUS / "eval" / "thorough.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert set(record["inputs"]) >= {"focal_name", "reference", "suite", "mutants", "obligations", "grid"}
        assert set(record["metadata"]) >= {"corpus_item", "stratum", "split", "suite_kind"}


class TestGeneratorMechanics:
    def test_the_split_is_keyed_and_deterministic(self) -> None:
        assert lib._bucket(1, "a") == lib._bucket(1, "a")
        assert lib._bucket(1, "a") != lib._bucket(2, "a")
        assert 0.0 <= lib._bucket(gen.GENERATOR_SEED, "tg-linear-00") < 1.0

    def test_a_mutation_site_that_does_not_exist_yields_nothing(self) -> None:
        assert lib._mutate("def f():\n    return 1\n", "relational", 0) is None

    def test_one_mutation_is_applied_at_a_time(self) -> None:
        """Two faults in one mutant make "killed" a weaker statement than it looks."""
        source = "def f(a, b):\n    return (a < b) and (a > 0)\n"
        first = lib._mutate(source, "relational", 0)
        second = lib._mutate(source, "relational", 1)
        assert first is not None and second is not None and first != second

    def test_behaviour_records_a_raise_as_behaviour(self) -> None:
        raising = "def f(n, k):\n    return n // 0\n"
        assert all(str(v).startswith(f"{lib.RAISE_MARKER}ZeroDivisionError") for v in lib._behaviour(raising, "f"))

    def test_the_raise_predicate_reads_only_the_marker_it_owns(self) -> None:
        """The marker was a bare `"!"` tested with `.startswith` at three call sites, so a
        reference value that legitimately began with `"!"` would have been misread as an
        exception at all three. One predicate, one constant."""
        assert lib.raises(f"{lib.RAISE_MARKER}ValueError") is True
        assert lib.raises("plain") is False
        assert lib.raises(0) is False and lib.raises(None) is False

    def test_case_lines_refuses_a_raising_value_rather_than_emitting_broken_code(self) -> None:
        """REGRESSION for a dead branch that carried a live trap.

        `_case_lines` used to emit `with pytest_raises():` for a raising reference value.
        That name is undefined in the generated suite (its header imports only the focal
        function) and in the runner (deliberately pytest-free), so a reachable version
        would have turned a "thorough" fixture into a NameError at import — silently
        reclassifying the corpus's known-GOOD suite as its known-BROKEN one. It was
        unreachable only because `_build_suites` filters raising indices out first, which
        is a precondition, and preconditions belong in the callee.
        """
        raising_reference = tuple([f"{lib.RAISE_MARKER}ZeroDivisionError"] * len(lib.GRID))
        with pytest.raises(ValueError, match="cannot pin a raising reference value"):
            lib._case_lines("f", raising_reference, [0])

    def test_the_weak_suite_picks_the_least_discriminating_point(self) -> None:
        """The unit behind the corpus-wide property: fewest kills wins, ties on index.

        Chosen from the whole assertable grid, not the covering set — for the 32 items that
        motivated this, the cover is a single index, so choosing within it leaves no choice
        to make and `weak` stayed identical to `thorough`.
        """
        mutants = [
            lib._Mutant("M1", "relational", "", False, (0, 1, 2)),
            lib._Mutant("M2", "relational", "", False, (0,)),
            lib._Mutant("M3", "arithmetic", "", True, ()),
        ]
        assert lib._weakest_index([0, 1, 2], mutants) == 1, "index 0 kills two; 1 and 2 kill one each"
        assert lib._weakest_index([0], mutants) == 0, "with one candidate there is no choice"

    def test_check_reports_a_missing_corpus(self, tmp_path: Path) -> None:
        problems = gen.check_corpus(tmp_path / "absent")
        assert problems and all("missing" in p for p in problems)

    def test_check_reports_drift(self, tmp_path: Path) -> None:
        gen.write_corpus(tmp_path)
        (tmp_path / "items.json").write_text("[]\n", encoding="utf-8")
        assert any("differs from a fresh generation" in p for p in gen.check_corpus(tmp_path))

    def test_main_write_then_check_round_trips(self, tmp_path: Path) -> None:
        assert gen.main(["--write", "--dir", str(tmp_path)]) == 0
        assert gen.main(["--check", "--dir", str(tmp_path)]) == 0

    def test_main_check_fails_on_an_empty_directory(self, tmp_path: Path) -> None:
        assert gen.main(["--check", "--dir", str(tmp_path / "nope")]) == 1


def _mutant_records(item: dict[str, Any]) -> list[lib._Mutant]:
    """Rehydrate the dataclasses `_covering_indices` expects from the committed JSON."""
    return [
        lib._Mutant(
            id=m["id"],
            kind=m["kind"],
            source=m["source"],
            equivalent=m["equivalent"],
            differs_at=tuple(m["differs_at"]),
        )
        for m in item["mutants"]
    ]
