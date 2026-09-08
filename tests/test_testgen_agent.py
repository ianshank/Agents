"""Tests for the agent-in-the-loop testgen pipeline target."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from eval_harness.config import load_config
from eval_harness.core._imports import CALLABLE_ALLOWLIST_ENV
from eval_harness.core.types import TESTGEN_EVIDENCE_KEY, EvalItem
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets.testgen_agent import (
    ATTEMPT_ID_KEY,
    PROMPT_HASH_KEY,
    SUITE_HASH_KEY,
    TestgenAgentConfig,
    TestgenAgentTarget,
)
from tests._testgen_agent_fixtures import KILLING_SUITE, mutating_spy
from tests.test_testgen_target import item as _inputs

bootstrap()

REPO = Path(__file__).resolve().parent.parent
THOROUGH = REPO / "corpora" / "testgen" / "v1" / "eval" / "thorough.jsonl"
AGENT_YAML = REPO / "config" / "testgen_agent_eval.yaml"
EMPTY_YAML = REPO / "config" / "testgen_agent_empty_eval.yaml"
DECK_A_YAML = REPO / "config" / "testgen_eval.yaml"


def _item(*, split: str = "holdout", suite: str = "SECRET_CORPUS_SUITE", **overrides: Any) -> EvalItem:
    payload = _inputs(suite)
    payload.update(overrides)
    return EvalItem(id="tg-agent", inputs=payload, metadata={"split": split})


def _killing(_view: EvalItem) -> str:
    return KILLING_SUITE


class TestHomeworkAttack:
    def test_generator_does_not_see_inputs_suite(self) -> None:
        seen: dict[str, Any] = {}

        def spy(view: EvalItem) -> str:
            seen["keys"] = set(view.inputs)
            seen["suite"] = view.inputs.get("suite")
            return KILLING_SUITE

        original = _item()
        out = TestgenAgentTarget(generate=spy).run(original)
        assert "suite" not in seen["keys"]
        assert seen["suite"] is None
        assert original.inputs["suite"] == "SECRET_CORPUS_SUITE"
        assert out.error is None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["mutants"]["killed"] == 1

    def test_mutating_the_view_does_not_poison_the_original_item(self) -> None:
        original = _item()
        snapshot = list(original.inputs["obligations"])
        out = TestgenAgentTarget(generate=mutating_spy).run(original)
        assert out.error is None
        assert original.inputs["obligations"] == snapshot
        assert "MUTATED_BY_GENERATOR" not in original.inputs["obligations"]

    def test_a_generator_that_only_copies_suite_cannot_see_it(self) -> None:
        def homework(view: EvalItem) -> str:
            return str(view.inputs["suite"])

        out = TestgenAgentTarget(generate=homework).run(_item())
        assert out.error is not None
        assert "suite" in (out.error or "") or "generator raised" in (out.error or "")
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0


class TestFailClosed:
    def test_missing_generator_is_empty_evidence_not_a_crash(self) -> None:
        out = TARGETS.create("testgen_agent", {"allowed_splits": ["holdout"]}).run(_item())
        assert out.error is not None
        assert "no generator" in (out.error or "")
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_empty_suite_is_malformed(self) -> None:
        out = TestgenAgentTarget(generate=lambda _view: "   ").run(_item())
        assert out.error is not None
        assert "malformed" in (out.error or "")
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_non_string_suite_is_malformed(self) -> None:
        out = TestgenAgentTarget(generate=lambda _view: 42).run(_item())  # type: ignore[arg-type, return-value]
        assert out.error is not None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_train_item_fails_when_only_holdout_is_allowed(self) -> None:
        out = TestgenAgentTarget(generate=_killing).run(_item(split="train"))
        assert out.error is not None
        assert "train" in (out.error or "")
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["collected"] == 0

    def test_missing_split_fails_closed(self) -> None:
        it = EvalItem(id="x", inputs=_inputs("SECRET"), metadata={})
        out = TestgenAgentTarget(generate=_killing).run(it)
        assert out.error is not None
        assert "metadata.split" in (out.error or "")


class TestExecution:
    def test_generated_killing_suite_is_executed(self) -> None:
        out = TestgenAgentTarget(generate=_killing).run(_item())
        evidence = out.metadata[TESTGEN_EVIDENCE_KEY]
        assert evidence["collected"] == 1
        assert evidence["mutants"]["killed"] == 1
        assert out.metadata[PROMPT_HASH_KEY]
        assert out.metadata[SUITE_HASH_KEY]
        assert out.metadata[ATTEMPT_ID_KEY]

    def test_two_runs_are_identical_when_the_fake_is_constant(self) -> None:
        target = TestgenAgentTarget(generate=_killing)
        assert target.is_deterministic() is True
        a = target.run(_item())
        b = target.run(_item())
        assert a.metadata[TESTGEN_EVIDENCE_KEY] == b.metadata[TESTGEN_EVIDENCE_KEY]
        assert a.metadata[SUITE_HASH_KEY] == b.metadata[SUITE_HASH_KEY]

    def test_execute_logs_hashes_not_the_suite_body(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="eval_harness.targets.testgen_agent"):
            out = TestgenAgentTarget(generate=_killing).run(_item())
        assert out.error is None
        text = caplog.text
        assert out.metadata[PROMPT_HASH_KEY] in text
        assert out.metadata[SUITE_HASH_KEY] in text
        assert out.metadata[ATTEMPT_ID_KEY] in text
        assert KILLING_SUITE not in text


class TestGeneratorPath:
    def test_unlisted_generator_path_is_refused_before_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "something_else")
        target = TestgenAgentTarget(generator_path="tests._testgen_agent_fixtures:killing_suite")
        out = target.run(_item())
        assert out.error is not None
        assert CALLABLE_ALLOWLIST_ENV in (out.error or "") or "could not be resolved" in (out.error or "")

    def test_allowlisted_path_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")
        target = TestgenAgentTarget(generator_path="tests._testgen_agent_fixtures:killing_suite")
        out = target.run(_item())
        assert out.error is None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["mutants"]["killed"] == 1
        assert target.is_deterministic() is None

    def test_generate_and_path_together_are_refused(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            TestgenAgentTarget(
                generate=_killing,
                generator_path="tests._testgen_agent_fixtures:killing_suite",
            )

    def test_malformed_path_fail_closes(self) -> None:
        out = TestgenAgentTarget(generator_path="no_colon_here").run(_item())
        assert out.error is not None
        assert "could not be resolved" in (out.error or "")

    def test_non_callable_path_fail_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")
        out = TestgenAgentTarget(generator_path="tests._testgen_agent_fixtures:NOT_A_GENERATOR").run(_item())
        assert out.error is not None
        assert "could not be resolved" in (out.error or "")

    def test_generator_path_is_cached_across_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CALLABLE_ALLOWLIST_ENV, "tests")
        target = TestgenAgentTarget(generator_path="tests._testgen_agent_fixtures:killing_suite")
        first = target.run(_item())
        second = target.run(_item())
        assert first.error is None
        assert second.error is None
        assert first.metadata[SUITE_HASH_KEY] == second.metadata[SUITE_HASH_KEY]


class TestConfig:
    def test_digest_chars_rejects_non_finite(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            TestgenAgentConfig(digest_chars=float("inf"))  # type: ignore[arg-type]

    def test_digest_chars_rejects_out_of_range(self) -> None:
        with pytest.raises(ValueError, match=r"\[8, 64\]"):
            TestgenAgentConfig(digest_chars=7)

    def test_empty_allowed_splits_rejected_at_config_time(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            TestgenAgentConfig(allowed_splits=())
        with pytest.raises(ValueError, match="at least one"):
            TestgenAgentConfig(allowed_splits=("",))
        with pytest.raises(ValueError, match="at least one"):
            TestgenAgentTarget(allowed_splits=())

    def test_prompt_preamble_is_hashed_into_the_prompt_digest(self) -> None:
        default = TestgenAgentTarget(generate=_killing).run(_item())
        other = TestgenAgentTarget(generate=_killing, prompt_preamble="held-constant other").run(_item())
        assert default.metadata[PROMPT_HASH_KEY] != other.metadata[PROMPT_HASH_KEY]
        assert default.metadata[SUITE_HASH_KEY] == other.metadata[SUITE_HASH_KEY]

    def test_alias_resolves(self) -> None:
        target = TARGETS.create("testgen-agent", {})
        assert isinstance(target, TestgenAgentTarget)

    def test_dict_signature_generator_is_invoked(self) -> None:
        def gen(inputs: dict[str, Any]) -> str:
            assert "suite" not in inputs
            return KILLING_SUITE

        out = TestgenAgentTarget(generate=gen).run(_item())  # type: ignore[arg-type]
        assert out.error is None
        assert out.metadata[TESTGEN_EVIDENCE_KEY]["mutants"]["killed"] == 1

    def test_non_mapping_inputs_fail_closed(self) -> None:
        it = EvalItem(id="x", inputs="nope", metadata={"split": "holdout"})  # type: ignore[arg-type]
        out = TestgenAgentTarget(generate=_killing).run(it)
        assert out.error is not None
        assert "mapping" in (out.error or "")

    def test_committed_agent_yaml_is_holdout_only_and_advisory(self) -> None:
        config = yaml.safe_load(AGENT_YAML.read_text(encoding="utf-8"))
        assert config["target"]["type"] == "testgen_agent"
        assert config["target"]["params"]["allowed_splits"] == ["holdout"]
        assert "train" not in config["target"]["params"]["allowed_splits"]
        assert config["dataset"]["params"]["path"].endswith("thorough.jsonl")
        rules = config["gate"]["rules"]
        assert all(rule.get("report_only") is True for rule in rules)

    def test_empty_baseline_yaml_loads_and_has_no_generator_path(self) -> None:
        cfg = load_config(EMPTY_YAML)
        assert cfg.target.type == "testgen_agent"
        assert cfg.target.params["allowed_splits"] == ["holdout"]
        assert "generator_path" not in cfg.target.params
        assert cfg.gate is not None
        assert cfg.gate.rules
        assert all(rule.report_only is True for rule in cfg.gate.rules)

    def test_deck_a_yaml_is_byte_stable_corpus_path(self) -> None:
        config = yaml.safe_load(DECK_A_YAML.read_text(encoding="utf-8"))
        assert config["target"]["type"] == "callable"
        assert config["target"]["params"]["path"] == "eval_harness.targets.testgen:run_generated_suite"


class TestHoldoutQuoting:
    def test_thorough_holdout_is_eleven_unique_corpus_items(self) -> None:
        rows = [json.loads(line) for line in THOROUGH.read_text(encoding="utf-8").splitlines() if line.strip()]
        holdout = [row for row in rows if row.get("metadata", {}).get("split") == "holdout"]
        ids = {row["metadata"]["corpus_item"] for row in holdout}
        assert len(holdout) == 11
        assert len(ids) == 11
