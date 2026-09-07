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

CORPUS = Path(__file__).resolve().parent.parent / "corpora" / "requirements" / "v1"


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
        assert {"contradictory", "stale", "mutated"} <= set(manifest["classes"])

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
