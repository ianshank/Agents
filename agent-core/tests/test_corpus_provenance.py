"""Human-vs-synthetic provenance for a GoldenSet. Never invents labels."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.config import ConfigError
from agent_core.corpus_provenance import (
    CorpusProvenanceConfig,
    corpus_problems,
    item_provenance,
    main,
    require_human_corpus,
)
from agent_core.golden import GoldenItem, GoldenSet


def _item(i: int, provenance: str | None = "human") -> GoldenItem:
    meta = {} if provenance is None else {"provenance": provenance}
    return GoldenItem(item_id=f"i{i}", text=f"t{i}", label=i % 2, meta=meta)


def test_config_rejects_identical_tokens() -> None:
    with pytest.raises(ConfigError):
        CorpusProvenanceConfig(human_value="x", synthetic_value="x")
    with pytest.raises(ConfigError):
        CorpusProvenanceConfig(meta_key="   ")
    with pytest.raises(ConfigError):
        CorpusProvenanceConfig(human_value="")
    with pytest.raises(ConfigError):
        CorpusProvenanceConfig(min_items=0)


def test_item_provenance_empty_when_unset() -> None:
    assert item_provenance({}) == ""
    cfg = CorpusProvenanceConfig(meta_key="src")
    assert item_provenance({"src": "human"}, cfg) == "human"


def test_undersized_and_synthetic_and_missing_are_problems() -> None:
    cfg = CorpusProvenanceConfig(min_items=4)
    gs = GoldenSet((_item(0, "human"), _item(1, "synthetic"), _item(2, None)))
    problems = corpus_problems(gs, cfg)
    assert any("need >= 4" in p for p in problems)
    assert any("synthetic" in p for p in problems)
    assert any("missing" in p for p in problems)
    with pytest.raises(ConfigError):
        require_human_corpus(gs, cfg)


def test_all_human_at_floor_passes() -> None:
    cfg = CorpusProvenanceConfig(min_items=2)
    gs = GoldenSet((_item(0), _item(1)))
    assert corpus_problems(gs, cfg) == ()
    require_human_corpus(gs, cfg)


def test_cli_fail_and_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gs = GoldenSet((_item(0),))
    path = tmp_path / "g.jsonl"
    path.write_text(gs.to_jsonl(), encoding="utf-8")
    assert main(["--jsonl", str(path), "--min-items", "2"]) == 2
    assert "FAIL" in capsys.readouterr().err
    assert main(["--jsonl", str(path), "--min-items", "1"]) == 0
    assert "PASS" in capsys.readouterr().out
