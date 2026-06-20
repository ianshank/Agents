"""Task-suite model + SDLC generator/snapshot tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flow_corpus.config import CorpusConfig
from flow_corpus.suites.base import TaskInstance, TaskSuite
from flow_corpus.suites.sdlc import build_sdlc_suite, load_suite, save_suite


def test_instance_rejects_correct_outside_space() -> None:
    with pytest.raises(ValidationError):
        TaskInstance(instance_id="i", domain="d", solution_space=("a", "b"), correct=("z",))


def test_instance_requires_a_wrong_answer() -> None:
    with pytest.raises(ValidationError):
        TaskInstance(instance_id="i", domain="d", solution_space=("a", "b"), correct=("a", "b"))


def test_instance_wrong_property() -> None:
    inst = TaskInstance(instance_id="i", domain="d", solution_space=("a", "b", "c"), correct=("a",))
    assert set(inst.wrong) == {"b", "c"}


def test_suite_rejects_mixed_domain() -> None:
    a = TaskInstance(instance_id="a", domain="x", solution_space=("a", "b"), correct=("a",))
    b = TaskInstance(instance_id="b", domain="y", solution_space=("a", "b"), correct=("a",))
    with pytest.raises(ValidationError):
        TaskSuite(domain="x", instances=(a, b))


def test_build_sdlc_suite_declared_size_and_determinism() -> None:
    cfg = CorpusConfig(declared_n_per_domain=50)
    s1 = build_sdlc_suite(cfg, seed=1)
    s2 = build_sdlc_suite(cfg, seed=1)
    assert len(s1) == 50
    assert s1.instances == s2.instances  # deterministic
    assert s1.domain == "sdlc"


def test_suite_jsonl_roundtrip(tmp_path) -> None:
    cfg = CorpusConfig(declared_n_per_domain=20)
    suite = build_sdlc_suite(cfg, seed=2)
    path = save_suite(suite, tmp_path / "sdlc.jsonl")
    loaded = load_suite(path)
    assert loaded.instances == suite.instances


def test_load_suite_rejects_empty_file(tmp_path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no valid task instances"):
        load_suite(empty)


def test_suite_rejects_duplicate_instance_ids() -> None:
    a = TaskInstance(instance_id="dup", domain="x", solution_space=("a", "b"), correct=("a",))
    b = TaskInstance(instance_id="dup", domain="x", solution_space=("a", "b"), correct=("b",))
    with pytest.raises(ValidationError):
        TaskSuite(domain="x", instances=(a, b))


def test_committed_snapshot_matches_generator() -> None:
    # Locks the committed data/suites/sdlc.jsonl to the generator's default output, so a
    # generator refactor that drifts the RNG sequence is caught.
    from flow_corpus.config import CorpusConfig

    assert build_sdlc_suite(CorpusConfig()).instances == load_suite().instances


def test_build_sdlc_suite_parameterised() -> None:
    cfg = CorpusConfig(declared_n_per_domain=10)
    suite = build_sdlc_suite(cfg, seed=1, space_size=6, max_difficulty=0.5)
    assert all(len(i.solution_space) == 6 for i in suite.instances)
    assert max(i.difficulty for i in suite.instances) <= 0.5


def test_build_sdlc_suite_validates_args() -> None:
    cfg = CorpusConfig(declared_n_per_domain=5)
    with pytest.raises(ValueError, match="space_size must be >= 2"):
        build_sdlc_suite(cfg, space_size=1)
    with pytest.raises(ValueError, match="max_difficulty"):
        build_sdlc_suite(cfg, max_difficulty=1.5)
