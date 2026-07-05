"""Tests for F-026 — Langfuse judge-prompt management."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from eval_harness.config.models import EvalConfig, PromptSourceConfig
from eval_harness.core.interfaces import Judge
from eval_harness.core.types import JudgeVerdict
from eval_harness.engine import EvalEngine
from eval_harness.langfuse_client import LangfuseClient, NullLangfuseClient, SDKLangfuseClient
from eval_harness.plugins import JUDGES, bootstrap
from eval_harness.prompts import resolve_prompt
from eval_harness.version import SCHEMA_VERSION


# A system-prompt-accepting judge that records what it was constructed with, so
# the from_config injection is observable without depending on a real LLM SDK.
@JUDGES.register("system_recording_judge")
class _SystemRecordingJudge(Judge):
    def __init__(self, system: str | None = None) -> None:
        self.system = system

    def evaluate(self, prompt: str, context: dict | None = None) -> JudgeVerdict:
        return JudgeVerdict(score=1.0, reasoning=self.system or "none")


class _PromptClient(NullLangfuseClient):
    def get_prompt(self, name, version=None, label=None):  # type: ignore[override]
        return f"REGISTRY::{name}:v{version}:l{label}"


# --- PromptSourceConfig validation ------------------------------------------


def test_yaml_source_requires_text():
    with pytest.raises(ValueError, match="text is required"):
        PromptSourceConfig(source="yaml")


def test_langfuse_source_requires_name():
    with pytest.raises(ValueError, match="name is required"):
        PromptSourceConfig(source="langfuse")


def test_invalid_source_rejected():
    with pytest.raises(ValueError, match=r"yaml.*langfuse"):
        PromptSourceConfig(source="bogus", text="x")


# --- resolve_prompt ----------------------------------------------------------


def test_resolve_yaml_returns_inline_text():
    spec = PromptSourceConfig(source="yaml", text="INLINE")
    assert resolve_prompt(spec, None) == "INLINE"
    assert resolve_prompt(spec, NullLangfuseClient()) == "INLINE"


def test_resolve_langfuse_falls_back_without_client():
    spec = PromptSourceConfig(source="langfuse", name="r", text="FALLBACK")
    assert resolve_prompt(spec, None) == "FALLBACK"


def test_resolve_langfuse_falls_back_when_unavailable():
    spec = PromptSourceConfig(source="langfuse", name="r", text="FALLBACK")
    assert resolve_prompt(spec, NullLangfuseClient()) == "FALLBACK"


def test_resolve_langfuse_returns_registry_text():
    spec = PromptSourceConfig(source="langfuse", name="r", version=3, label="prod", text="FB")
    assert resolve_prompt(spec, _PromptClient()) == "REGISTRY::r:v3:lprod"


def test_resolve_langfuse_without_text_returns_none_on_miss():
    spec = PromptSourceConfig(source="langfuse", name="r")  # no fallback text
    assert resolve_prompt(spec, NullLangfuseClient()) is None


# --- client surface ----------------------------------------------------------


def test_base_client_get_prompt_default_none():
    # The non-abstract default keeps third-party subclasses working: get_prompt
    # is not in the ABC's abstractmethods, so a subclass need not implement it.
    assert "get_prompt" not in LangfuseClient.__abstractmethods__
    assert NullLangfuseClient().get_prompt("x") is None


@patch("langfuse.Langfuse")
def test_sdk_get_prompt_returns_text(mock_langfuse_class):
    mock_lf = mock_langfuse_class.return_value
    mock_lf.get_prompt.return_value = MagicMock(prompt="HELLO")
    client = SDKLangfuseClient()
    assert client.get_prompt("r", version=2, label="prod") == "HELLO"
    mock_lf.get_prompt.assert_called_once_with("r", version=2, label="prod")


@patch("langfuse.Langfuse")
def test_sdk_get_prompt_fails_safe(mock_langfuse_class):
    mock_lf = mock_langfuse_class.return_value
    mock_lf.get_prompt.side_effect = RuntimeError("network down")
    client = SDKLangfuseClient()
    assert client.get_prompt("r") is None


@patch("langfuse.Langfuse")
def test_sdk_get_prompt_non_string_returns_none(mock_langfuse_class):
    mock_lf = mock_langfuse_class.return_value
    mock_lf.get_prompt.return_value = MagicMock(prompt=12345)  # not a str
    client = SDKLangfuseClient()
    assert client.get_prompt("r") is None


# --- engine.from_config injection -------------------------------------------


def _base_config(**overrides: Any) -> EvalConfig:
    data: dict[str, Any] = dict(
        schema_version=SCHEMA_VERSION,
        dataset={"type": "inline", "params": {}},
        target={"type": "echo", "params": {}},
        judge={"type": "system_recording_judge", "params": {}},
    )
    data.update(overrides)
    return EvalConfig.model_validate(data)


def _system_from(engine: EvalEngine) -> str | None:
    judge = engine.judge
    assert isinstance(judge, _SystemRecordingJudge)
    return cast(str | None, cast(Any, judge).system)


def test_from_config_injects_resolved_system_prompt():
    bootstrap()
    cfg = _base_config(
        judge_prompt={"source": "langfuse", "name": "rubric", "text": "FB"},
    )
    engine = EvalEngine.from_config(cfg, langfuse_client=_PromptClient())
    assert _system_from(engine) == "REGISTRY::rubric:vNone:lNone"


def test_from_config_falls_back_to_yaml_text():
    bootstrap()
    cfg = _base_config(judge_prompt={"source": "yaml", "text": "INLINE"})
    engine = EvalEngine.from_config(cfg, langfuse_client=None)
    assert _system_from(engine) == "INLINE"


def test_from_config_without_judge_prompt_leaves_params_untouched():
    bootstrap()
    cfg = _base_config(judge={"type": "system_recording_judge", "params": {"system": "RAW"}})
    engine = EvalEngine.from_config(cfg)
    assert _system_from(engine) == "RAW"


def test_from_config_resolved_none_does_not_inject():
    bootstrap()
    # langfuse spec with no fallback text + no client -> resolve returns None ->
    # the judge keeps its own param-supplied system.
    cfg = _base_config(
        judge={"type": "system_recording_judge", "params": {"system": "RAW"}},
        judge_prompt={"source": "langfuse", "name": "rubric"},
    )
    engine = EvalEngine.from_config(cfg, langfuse_client=None)
    assert _system_from(engine) == "RAW"
