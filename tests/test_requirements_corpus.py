#!/usr/bin/env python3
"""Tests for the frozen requirements corpus and its generator (task 2).

Pins the spec's corpus contract: byte-identical regeneration, per-item hashes, the
keyed holdout split, the negative-control classes, and that no target-visible field
marks a control.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import gen_requirements_corpus as gen
import pytest

from eval_harness.config import load_config
from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY, EvalItem
from eval_harness.engine import EvalEngine
from eval_harness.core.types import RunContext
from eval_harness.langfuse_client import NullLangfuseClient
from eval_harness.plugins import SCORERS
from eval_harness.targets.provenance import (
    MappingEvidenceStore,
    ProvenanceRecorderTarget,
    verify_provenance,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "corpora" / "requirements" / "v1"
SHIPPED_CONFIG = REPO_ROOT / "config" / "requirements_eval.yaml"


def _store(contents: dict[str, str]) -> MappingEvidenceStore:
    return MappingEvidenceStore({k: v.encode("utf-8") for k, v in contents.items()})


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = json.loads((CORPUS / "items.json").read_text(encoding="utf-8"))
    return payload


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return payload


class TestCommittedCorpus:
    def test_the_committed_corpus_regenerates_byte_identically(self) -> None:
        assert gen.check_corpus(CORPUS) == []

    def test_the_manifest_hash_matches_every_item(self, items: list[dict], manifest: dict) -> None:
        for item in items:
            assert manifest["items"][item["epic_id"]] == gen._item_hash(item)

    def test_the_corpus_size_and_split(self, items: list[dict], manifest: dict) -> None:
        assert manifest["item_count"] == gen.ITEM_COUNT == len(items)
        splits = manifest["splits"]
        assert 0 < splits["holdout"] < splits["train"]

    def test_every_item_declares_a_gold_set_and_sources(self, items: list[dict]) -> None:
        for item in items:
            assert item["gold_ac"], item["epic_id"]
            assert item["evidence_sources"], item["epic_id"]


class TestNegativeControls:
    def test_the_control_classes_are_present(self, manifest: dict) -> None:
        """Read from the generator's declaration so a new class cannot be added untested."""
        assert set(gen.CONTROL_CLASSES) <= set(manifest["classes"])
        assert set(manifest["classes"]) <= set(gen.CONTROL_CLASSES) | {gen.ORDINARY_CLASS}

    def test_controls_are_not_distinguishable_by_target_visible_fields(self, items: list[dict]) -> None:
        """Spec: no field the target sees marks a negative control."""
        target_visible = {"epic_id", "domain", "title", "statement", "evidence_sources", "declared_tests"}
        ordinary = [i for i in items if i["control"] == "ordinary"]
        for item in items:
            assert target_visible <= set(item), item["epic_id"]
        for key in ("domain",):
            assert {i[key] for i in items if i["control"] != "ordinary"} <= {i[key] for i in ordinary}

    def test_the_control_class_never_reaches_the_record_the_target_is_handed(
        self, items: list[dict]
    ) -> None:
        """The check above reads the corpus item; this reads what the *harness* loads.

        ``EvalItem.metadata`` is handed to the target with everything else, so a
        ``control`` key there would let a system under test behave differently on a
        negative control — and the corpus would stop measuring what it claims to. Scanned
        recursively rather than by key lookup: nesting it deeper would leak it just as well.
        """

        def flatten(node: Any) -> Iterator[tuple[str, Any]]:
            if isinstance(node, dict):
                for key, value in node.items():
                    yield str(key), value
                    yield from flatten(value)
            elif isinstance(node, list):
                for value in node:
                    yield from flatten(value)

        classes = set(gen.CONTROL_CLASSES) | {gen.ORDINARY_CLASS}
        for record in gen.build_eval_records(items):
            for key, value in flatten(record):
                assert key != "control", f"{record['id']} leaks its control class"
                if isinstance(value, str):
                    assert value not in classes, f"{record['id']} leaks {value!r} under {key!r}"

    def test_the_mutated_controls_drifted_bytes_diverge_from_the_recorded_hash(self, items: list[dict]) -> None:
        """The mutated items exist to prove the verification pass notices drift."""
        mutated = [i for i in items if i["control"] == "mutated"]
        assert mutated, "no mutated-evidence controls"
        for item in mutated:
            # At least one source's re-fetched bytes must differ from the recorded hash.
            assert any(
                hashlib.sha256(item["drifted_bytes"][sid].encode()).hexdigest() != recorded
                for sid, recorded in item["recorded_hashes"].items()
            ), item["epic_id"]

    def test_only_the_mutated_controls_drift_when_the_run_s_own_records_are_reverified(
        self, items: list[dict]
    ) -> None:
        """The end-to-end claim task 2.3 actually makes: not that the corpus *contains*
        mutated bytes, but that the verification pass *detects* them.

        Records are produced the way a real run produces them — by the wrapper, fetching
        through the capture store — and then re-verified against the drift store. Any
        other item drifting would mean the corpus reports drift that never happened.
        """
        capture = _store(gen.build_store(items))
        drifted = _store(gen.build_store(items, key="drifted_bytes"))
        target = ProvenanceRecorderTarget(
            inner_spec={"type": "echo", "params": {"output_key": "generated"}},
            store_contents={k: v for k, v in gen.build_store(items).items()},
        )
        by_class: dict[str, int] = {}
        for record, item in zip(gen.build_eval_records(items), items, strict=True):
            out = target.run(EvalItem(id=record["id"], inputs=record["inputs"], expected=record["expected"]))
            records = out.metadata[REQUIREMENTS_EVIDENCE_KEY]
            assert verify_provenance(records, capture) == [], f"{item['epic_id']} drifted against its own capture"
            failures = verify_provenance(records, drifted)
            by_class[item["control"]] = by_class.get(item["control"], 0) + len(failures)
        assert by_class["mutated"] == len([i for i in items if i["control"] == "mutated"])
        assert all(count == 0 for cls, count in by_class.items() if cls != "mutated"), by_class


class TestShippedJourney:
    """End to end over the shipped config: dataset -> provenance wrapper -> four scorers.

    The unit tests prove each scorer in isolation; this proves the documented command
    (`eval-harness run --config config/requirements_eval.yaml`) actually runs. It did not:
    the config named an empty evidence store, so every item raised at retrieval — a break
    no unit test could see, because none of them reads the config.
    """

    @pytest.fixture
    def run(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        # The config names its dataset and store relative to the repository root, the way
        # the documented command is run.
        monkeypatch.chdir(REPO_ROOT)
        config = load_config(str(SHIPPED_CONFIG))
        return EvalEngine.from_config(config, langfuse_client=NullLangfuseClient()).run()

    def test_every_item_completes_without_a_target_error(self, run: Any) -> None:
        assert [r.item.id for r in run.items if r.output.error] == []

    def test_all_four_scorers_report_over_the_whole_train_split(self, run: Any) -> None:
        assert set(run.aggregate) == {
            "req_ac_recall",
            "req_scope_hallucination",
            "req_traceability_closure",
            "req_semantic_diversity",
        }
        train = gen.split_records(gen._with_split(gen.build_items()))["train"]
        assert 0 < len(train) < gen.ITEM_COUNT
        assert all(agg.count == len(train) for agg in run.aggregate.values())

    def test_the_shipped_config_never_reads_the_sequestered_split(self, run: Any) -> None:
        """Task 2.5. A ``split`` label on a row is not a holdout while the config loads
        every row in the file — nothing in a dataset spec filters on metadata. Two files
        is what makes sequestration hold by default rather than by remembering to."""
        scored = {r.item.id for r in run.items}
        holdout = {r["id"] for r in gen.split_records(gen._with_split(gen.build_items()))["holdout"]}
        assert holdout, "no sequestered split"
        assert scored.isdisjoint(holdout)

    def test_no_scorer_reports_not_applicable_for_the_whole_corpus(self, run: Any) -> None:
        """ANTI-VACUOUS: a `pass_rate` of None across the board is the shape this had."""
        assert all(agg.pass_rate is not None for agg in run.aggregate.values())

    def test_the_journey_separates_items_rather_than_scoring_them_alike(self, run: Any) -> None:
        recall = {s.value for r in run.items for s in r.scores if s.name == "req_ac_recall"}
        assert len(recall) > 1, "every item scores identical recall — the journey measures nothing"

    def test_the_evidence_wrapper_recorded_a_pinned_source_for_every_item(self, run: Any) -> None:
        for result in run.items:
            records = result.output.metadata[REQUIREMENTS_EVIDENCE_KEY]
            assert records, result.item.id
            assert all(r["pinnable"] and r["content_sha256"] for r in records), result.item.id


class TestStandinGeneratorOutput:
    """The stand-in exists so the shipped journey scores something. If it degenerates to
    all-perfect or all-zero, the journey stops distinguishing a working scorer from a
    broken one — which is the failure mode the journey test below refuses."""

    def test_the_standin_never_cites_a_source_the_wrapper_could_record(self) -> None:
        items = gen.build_items()
        declared = {s["source_id"] for item in items for s in item["evidence_sources"]}
        assert gen.STANDIN_UNRECORDED_SOURCE not in declared

    def test_recall_is_not_uniformly_perfect_across_the_corpus(self) -> None:
        items = gen.build_items()
        ratios = set()
        for ordinal, item in enumerate(items):
            covered = {ac for req in gen.build_standin(item, ordinal)["requirements"] for ac in req["covers"]}
            ratios.add(len(covered & {ac["id"] for ac in item["gold_ac"]}) / len(item["gold_ac"]))
        assert len(ratios) > 1, "every epic scores identical recall — the stand-in proves nothing"

    def test_some_requirements_are_unsupported_and_some_are_not(self) -> None:
        items = gen.build_items()
        unsupported = [
            any(
                gen.STANDIN_UNRECORDED_SOURCE in req["evidence_links"]
                for req in gen.build_standin(i, o)["requirements"]
            )
            for o, i in enumerate(items)
        ]
        assert any(unsupported) and not all(unsupported)

    def test_every_control_class_changes_what_the_scorer_reports(self) -> None:
        """ANTI-VACUOUS. A negative control that scores exactly like an ordinary item is
        decoration: the corpus would claim to exercise contradiction and staleness while
        proving neither. Each class must therefore leave a distinct, checkable trace.

        Contradictory: some requirement asserts a claim another recorded source denies.
        Stale: a claim the superseded revision no longer supports becomes unsupported,
        with no contradiction. Ordinary: neither.
        """
        items = gen._with_split(gen.build_items())
        target = ProvenanceRecorderTarget(
            inner_spec={"type": "echo", "params": {"output_key": "generated"}},
            store_contents=gen.build_store(items),
        )
        scorer = SCORERS.create("req_scope_hallucination")
        ctx = RunContext(config=None)
        seen: dict[str, set[tuple[bool, bool]]] = {}
        for record, item in zip(gen.build_eval_records(items), items, strict=True):
            eval_item = EvalItem(id=record["id"], inputs=record["inputs"], expected=record["expected"])
            result = scorer.score(eval_item, target.run(eval_item), ctx)
            trace = (bool(result.metadata["contradiction_citations"]), bool(result.metadata["unsupported"]))
            seen.setdefault(item["control"], set()).add(trace)
        assert seen["contradictory"] == {(True, True)}
        assert seen["stale"] == {(False, True)}
        assert all(not contradicted for contradicted, _ in seen["ordinary"])
        assert (False, False) in seen["ordinary"], "no ordinary item scores cleanly"

    def test_the_standin_asserts_a_claim_no_source_supports(self) -> None:
        """The spec's unsupported-constraint scenario, exercised against a source that IS
        recorded — otherwise only the citation check is ever proven."""
        items = gen.build_items()
        supported = {c for i in items for s in i["evidence_sources"] for c in s["supports"]}
        ungrounded = [
            req
            for ordinal, item in enumerate(items)
            for req in gen.build_standin(item, ordinal)["requirements"]
            if req["claim"] not in supported and gen.STANDIN_UNRECORDED_SOURCE not in req["evidence_links"]
        ]
        assert ungrounded, "no requirement asserts an unsupported claim against a recorded source"
        assert gen.CLAIM_LATENCY_BUDGET not in supported

    def test_the_standin_declares_its_generation_temperature(self) -> None:
        """A diversity score without one is uninterpretable by contract."""
        standin = gen.build_standin(gen.build_items()[0], 0)
        assert standin["generation_temperature"] == gen.STANDIN_TEMPERATURE


class TestGeneratorCli:
    def test_write_then_check_round_trip(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        assert gen.main(["--check", "--dir", str(out)]) == 0

    def test_check_flags_a_hand_edit(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        items_path = out / "items.json"
        items_path.write_text(
            items_path.read_text(encoding="utf-8").replace('"billing"', '"hacked"', 1),
            encoding="utf-8",
        )
        assert gen.main(["--check", "--dir", str(out)]) == 1

    def test_check_names_every_missing_artifact_rather_than_stopping_at_the_first(self, tmp_path: Path) -> None:
        """An absent corpus must report every artifact ``--write`` would emit."""
        problems = gen.check_corpus(tmp_path / "never-written")
        assert len(problems) == len(gen.generated_artifacts())
        assert all("is missing" in problem for problem in problems)

    @pytest.mark.parametrize("relative", sorted(gen.generated_artifacts()))
    def test_check_flags_each_artifact_when_deleted(self, tmp_path: Path, relative: str) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        (out / relative).unlink()
        problems = gen.check_corpus(out)
        assert [p for p in problems if relative.split("/")[-1] in p and "is missing" in p]
        assert gen.main(["--check", "--dir", str(out)]) == 1

    def test_check_flags_a_hand_edited_eval_dataset(self, tmp_path: Path) -> None:
        """The harness-loadable mirror is generated too; editing it must not go unnoticed."""
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        eval_path = out / "eval" / "train.jsonl"
        first_id = json.loads(eval_path.read_text(encoding="utf-8").splitlines()[0])["id"]
        eval_path.write_text(eval_path.read_text(encoding="utf-8").replace(first_id, "req-99", 1), encoding="utf-8")
        problems = gen.check_corpus(out)
        assert [p for p in problems if "train.jsonl" in p and "differs" in p]

    def test_the_capture_store_serves_the_bytes_the_recorded_hashes_cover(self) -> None:
        """An ordinary run must verify clean, or every item would look like it drifted."""
        items = gen.build_items()
        store = gen.build_store(items)
        for item in items:
            for source_id, captured in item["evidence_bytes"].items():
                assert store[source_id] == captured

    def test_the_drift_store_diverges_for_the_mutated_controls_and_nothing_else(self) -> None:
        items = gen.build_items()
        drifted = gen.build_store(items, key="drifted_bytes")
        divergent = {
            item["control"]
            for item in items
            if any(drifted[sid] != captured for sid, captured in item["evidence_bytes"].items())
        }
        assert divergent == {"mutated"}

    @pytest.mark.parametrize("key", ["evidence_bytes", "drifted_bytes"])
    def test_every_declared_source_is_servable(self, key: str) -> None:
        """A declared source the store cannot serve fails the run at retrieval time."""
        items = gen.build_items()
        store = gen.build_store(items, key=key)
        for item in items:
            for source in item["evidence_sources"]:
                assert source["source_id"] in store, item["epic_id"]

    def test_the_split_is_computed_on_copies_not_by_rewriting_the_caller_s_items(self) -> None:
        """``_with_split`` returning its argument mutated would corrupt a reused list."""
        built = gen.build_items()
        split = gen._with_split(built)
        assert all("split" not in item for item in built)
        assert all(item["split"] in {"train", "holdout"} for item in split)
