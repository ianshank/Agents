"""Frozen answer-quality corpus: regeneration, strata, keyed holdout, advisory config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import _answer_quality_corpus_lib as lib
import gen_answer_quality_corpus as gen
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS = REPO_ROOT / "corpora" / "answer_quality" / "v1"
SHIPPED_CONFIG = REPO_ROOT / "config" / "answer_quality_eval.yaml"


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
            assert manifest["items"][item["item_id"]] == lib.item_hash(item)

    def test_every_stratum_is_represented(self, manifest: dict) -> None:
        assert set(manifest["strata"]) == set(lib.STRATA)
        assert manifest["item_count"] == len(lib.STRATA) * lib.ITEMS_PER_STRATUM

    def test_a_holdout_split_exists_and_is_a_minority(self, manifest: dict) -> None:
        splits = manifest["splits"]
        assert 0 < splits["holdout"] < splits["train"]

    def test_unrecovered_items_are_present(self, items: list[dict]) -> None:
        assert any(item["unrecovered_tool_error"] for item in items)


class TestGenerator:
    def test_write_then_check_is_clean(self, tmp_path: Path) -> None:
        gen.write_corpus(tmp_path)
        assert gen.check_corpus(tmp_path) == []

    def test_check_reports_drift(self, tmp_path: Path) -> None:
        gen.write_corpus(tmp_path)
        (tmp_path / "items.json").write_text("{}\n", encoding="utf-8")
        assert gen.check_corpus(tmp_path)

    def test_check_reports_missing(self, tmp_path: Path) -> None:
        problems = gen.check_corpus(tmp_path)
        assert any("missing" in problem for problem in problems)

    def test_main_write_and_check(self, tmp_path: Path) -> None:
        assert gen.main(["--write", "--dir", str(tmp_path)]) == 0
        assert gen.main(["--check", "--dir", str(tmp_path)]) == 0

    def test_main_check_fails_on_drift(self, tmp_path: Path) -> None:
        gen.write_corpus(tmp_path)
        (tmp_path / "manifest.json").write_text("{}\n", encoding="utf-8")
        assert gen.main(["--check", "--dir", str(tmp_path)]) == 1


class TestShippedConfig:
    def test_every_gate_rule_is_advisory(self) -> None:
        import yaml

        data = yaml.safe_load(SHIPPED_CONFIG.read_text(encoding="utf-8"))
        rules = ((data.get("gate") or {}).get("rules")) or []
        assert rules
        assert all(rule.get("report_only") is True for rule in rules)
        assert data["target"]["type"] == "replay"
