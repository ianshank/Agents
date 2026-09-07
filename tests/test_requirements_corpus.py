#!/usr/bin/env python3
"""Tests for the frozen requirements corpus and its generator (task 2).

Pins the spec's corpus contract: byte-identical regeneration, per-item hashes, the
keyed holdout split, the negative-control classes, and that no target-visible field
marks a control.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_requirements_corpus as gen
import pytest

from eval_harness.config import load_config
from eval_harness.core.types import REQUIREMENTS_EVIDENCE_KEY
from eval_harness.engine import EvalEngine
from eval_harness.langfuse_client import NullLangfuseClient

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "corpora" / "requirements" / "v1"
SHIPPED_CONFIG = REPO_ROOT / "config" / "requirements_eval.yaml"


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

    def test_the_mutated_controls_store_bytes_diverge_from_the_recorded_hash(self, items: list[dict]) -> None:
        """The mutated items exist to prove the verification pass notices drift."""
        import hashlib

        mutated = [i for i in items if i["control"] == "mutated"]
        assert mutated, "no mutated-evidence controls"
        for item in mutated:
            # At least one source's served bytes must differ from the recorded hash.
            assert any(
                hashlib.sha256(item["store_bytes"][sid].encode()).hexdigest() != recorded
                for sid, recorded in item["recorded_hashes"].items()
            ), item["epic_id"]


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

    def test_all_four_scorers_report_over_the_whole_corpus(self, run: Any) -> None:
        assert set(run.aggregate) == {
            "req_ac_recall",
            "req_scope_hallucination",
            "req_traceability_closure",
            "req_semantic_diversity",
        }
        train_count = sum(1 for item in gen._with_split(gen.build_items()) if item["split"] == "train")
        assert all(agg.count == train_count for agg in run.aggregate.values())

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
        eval_path = out / "eval" / "items.jsonl"
        eval_path.write_text(eval_path.read_text(encoding="utf-8").replace("req-00", "req-99", 1), encoding="utf-8")
        problems = gen.check_corpus(out)
        assert [p for p in problems if "items.jsonl" in p and "differs" in p]

    def test_the_evidence_store_serves_the_bytes_the_sources_resolve_to(self) -> None:
        """A mutated control must be served its mutated bytes, or it cannot demonstrate drift."""
        items = gen.build_items()
        store = gen.build_store(items)
        mutated = [i for i in items if i["control"] == "mutated"]
        assert mutated
        for item in mutated:
            for source_id, served in item["store_bytes"].items():
                assert store[source_id] == served
            assert any(store[sid] != original for sid, original in item["evidence_bytes"].items())

    def test_every_declared_source_is_servable(self) -> None:
        """A declared source the store cannot serve fails the run at retrieval time."""
        items = gen.build_items()
        store = gen.build_store(items)
        for item in items:
            for source in item["evidence_sources"]:
                assert source["source_id"] in store, item["epic_id"]

    def test_the_split_is_computed_on_copies_not_by_rewriting_the_caller_s_items(self) -> None:
        """``_with_split`` returning its argument mutated would corrupt a reused list."""
        built = gen.build_items()
        split = gen._with_split(built)
        assert all("split" not in item for item in built)
        assert all(item["split"] in {"train", "holdout"} for item in split)
