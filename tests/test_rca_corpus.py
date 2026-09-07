#!/usr/bin/env python3
"""Tests for the frozen RCA corpus and its generator (add-rca-eval-matrix task 2).

The corpus is generated, never scraped; these tests pin the properties the spec makes
load-bearing: byte-identical regeneration, per-item hashes, the keyed holdout split,
shape-identical negative controls, load-time rejection rules, and the calibrated
baseline-difficulty bands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_rca_corpus as gen
import pytest

import _rca_corpus_lib as lib  # isort: skip

CORPUS = Path(__file__).resolve().parent.parent / "corpora" / "rca" / "v1"


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
            assert manifest["items"][item["instance_id"]] == lib.item_hash(item)

    def test_every_class_and_stratum_is_represented(self, manifest: dict) -> None:
        assert set(manifest["classes"]) == set(lib.ITEM_CLASSES)
        assert manifest["item_count"] == len(lib.ITEM_CLASSES) * len(lib.STRATA) * gen.ITEMS_PER_CELL

    def test_a_holdout_split_exists_and_is_a_minority(self, manifest: dict) -> None:
        splits = manifest["splits"]
        assert 0 < splits["holdout"] < splits["train"]

    def test_every_item_is_valid_under_the_load_rules(self, items: list[dict]) -> None:
        for item in items:
            assert lib.validate_item(item) == [], item["instance_id"]


class TestNegativeControls:
    def test_unanswerable_items_are_present_and_unmarked(self, items: list[dict], manifest: dict) -> None:
        """Spec: no target-visible field distinguishes an unanswerable item."""
        unanswerable = [i for i in items if not i["correct"]]
        assert unanswerable, "the corpus carries no negative controls"
        assert manifest["unanswerable"] == len(unanswerable)
        target_visible = {"instance_id", "timezone", "candidates", "onset", "telemetry", "difficulty", "noise"}
        for item in unanswerable:
            # The keys a target can see are exactly the answerable items' keys.
            assert target_visible <= set(item)
            for key in ("difficulty", "noise", "timezone"):
                assert item[key] in {i[key] for i in items if i["correct"]}, key

    def test_multi_cause_items_are_present(self, items: list[dict]) -> None:
        assert any(len(i["correct"]) > 1 for i in items)


class TestLoadRejection:
    def test_an_item_without_a_candidate_set_is_rejected(self) -> None:
        item = {"instance_id": "x", "timezone": "UTC", "correct": ["a"], "onset": "2026-03-04T11:42:00+00:00"}
        assert any("candidates" in p for p in lib.validate_item(item))

    def test_an_item_without_a_timezone_is_rejected(self) -> None:
        item = {"instance_id": "x", "candidates": ["a"], "correct": [], "onset": "2026-03-04T11:42:00+00:00"}
        assert any("timezone" in p for p in lib.validate_item(item))

    def test_a_cause_outside_the_candidate_set_is_rejected(self) -> None:
        item = {
            "instance_id": "x",
            "timezone": "UTC",
            "candidates": ["a"],
            "correct": ["not-in-set"],
            "onset": "2026-03-04T11:42:00+00:00",
        }
        assert any("outside the candidate set" in p for p in lib.validate_item(item))


class TestCalibration:
    def test_the_manifest_records_measured_baseline_accuracy(self, manifest: dict) -> None:
        measured = manifest["baseline_strict_ac1"]
        assert measured, "the manifest must carry the baseline's measured per-cell AC@1"
        # The calibration the bands encode: easy solves, hard declines, and the
        # hard-negative confound beats the baseline more often than not.
        assert measured["single/s0"] == 1.0
        assert measured["single/s2"] == 0.0
        assert measured["hard-negative/s0"] < 0.5
        assert measured["unanswerable/s0"] == 0.0

    def test_the_band_gate_accepts_the_fresh_measurement(self, items: list[dict]) -> None:
        assert gen.check_baseline_bands(items) == []

    def test_the_band_gate_catches_a_trivialised_corpus(
        self, items: list[dict], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If every cell measured 1.0, the gate must fail — the bands are not decorative."""
        import eval_harness.targets.rca_baseline as baseline_mod

        class _TrivialTarget:
            def __init__(self) -> None:
                pass

            def run(self, ev: Any) -> Any:
                from eval_harness.core.types import TargetOutput

                return TargetOutput(output={"ranked": list(ev.inputs["candidates"])})

        # monkeypatch.setattr keeps the substitution visible and reverts it, unlike a raw
        # assignment (which mypy also rightly rejects as a type mismatch).
        monkeypatch.setattr(baseline_mod, "RcaMaxZBaselineTarget", _TrivialTarget)
        problems = gen.check_baseline_bands(items)
        assert problems, "a trivialised corpus must fail the band gate"


class TestGeneratorCli:
    def test_write_then_check_round_trip(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        assert (out / "items.json").is_file()
        assert (out / "manifest.json").is_file()
        assert (out / "eval" / "items.jsonl").is_file()
        assert gen.main(["--check", "--dir", str(out)]) == 0

    def test_check_flags_a_missing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        (out / "manifest.json").unlink()
        assert gen.main(["--check", "--dir", str(out)]) == 1

    def test_check_flags_a_hand_edit(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus"
        assert gen.main(["--write", "--dir", str(out)]) == 0
        items_path = out / "items.json"
        items_path.write_text(
            items_path.read_text(encoding="utf-8").replace('"svc-api"', '"svc-hacked"', 1),
            encoding="utf-8",
        )
        assert gen.main(["--check", "--dir", str(out)]) == 1

    def test_write_refuses_an_invalid_generation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A generator defect that produces an unloadable item aborts the write."""
        real_build_item = lib.build_item

        def broken_build_item(spec: lib.ItemSpec, seed: int) -> dict[str, Any]:
            item: dict[str, Any] = real_build_item(spec, seed)
            if spec.item_id.endswith("-00"):
                item = {k: v for k, v in item.items() if k != "candidates"}
            return item

        monkeypatch.setattr(gen, "build_item", broken_build_item)
        with pytest.raises(SystemExit):
            gen.write_corpus(tmp_path / "corpus")
