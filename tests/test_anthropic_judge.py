"""Mocked tests for the optional live AnthropicJudge (no network, no SDK required).

The judge is marked ``# pragma: no cover`` (it needs the anthropic SDK + network in
production), so these tests exist to verify the parse path and the Opus-4.8 contract
that ``temperature`` is omitted unless explicitly set — not to move the coverage gate.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

from eval_harness.judges import AnthropicJudge
from eval_harness.plugins import JUDGES


def _text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _judge_with_fake_sdk(monkeypatch, **kwargs) -> AnthropicJudge:
    fake = types.ModuleType("anthropic")
    fake.Anthropic = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return AnthropicJudge(**kwargs)


def test_registered_in_judges_registry():
    assert "anthropic" in JUDGES.names()
    assert "claude" in JUDGES  # alias resolves via __contains__


def test_parses_score_and_reasoning(monkeypatch):
    judge = _judge_with_fake_sdk(monkeypatch, model="claude-opus-4-8")
    resp = MagicMock()
    resp.content = [_text_block('Here: {"score": 0.8, "reasoning": "candid"}')]
    judge.client.messages.create.return_value = resp

    verdict = judge.evaluate("is this sycophantic?")
    assert verdict.score == 0.8
    assert verdict.reasoning == "candid"


def test_temperature_omitted_by_default(monkeypatch):
    judge = _judge_with_fake_sdk(monkeypatch)
    resp = MagicMock()
    resp.content = [_text_block('{"score": 0.1}')]
    judge.client.messages.create.return_value = resp

    judge.evaluate("prompt")
    _, kwargs = judge.client.messages.create.call_args
    assert "temperature" not in kwargs  # rejected on Opus 4.8 / 4.7


def test_malformed_json_returns_default_verdict(monkeypatch):
    judge = _judge_with_fake_sdk(monkeypatch)
    resp = MagicMock()
    resp.content = [_text_block("no json here")]
    judge.client.messages.create.return_value = resp

    verdict = judge.evaluate("prompt")
    assert verdict.score == 0.0
    assert "Failed to parse" in verdict.reasoning


def test_missing_score_key_is_clean_zero_verdict(monkeypatch):
    # Parseable JSON without a score mirrors OpenAIJudge: a 0.0 verdict, not a parse failure.
    judge = _judge_with_fake_sdk(monkeypatch)
    resp = MagicMock()
    resp.content = [_text_block('{"reasoning": "no score field"}')]
    judge.client.messages.create.return_value = resp

    verdict = judge.evaluate("prompt")
    assert verdict.score == 0.0
    assert verdict.reasoning == "no score field"
    assert "Failed to parse" not in verdict.reasoning


def test_temperature_forwarded_when_set(monkeypatch):
    judge = _judge_with_fake_sdk(monkeypatch, temperature=0.0)
    resp = MagicMock()
    resp.content = [_text_block('{"score": 0.2}')]
    judge.client.messages.create.return_value = resp

    judge.evaluate("prompt")
    _, kwargs = judge.client.messages.create.call_args
    assert kwargs["temperature"] == 0.0


# --------------------------------------------------------------------------
# The `client=` dependency-injection seam (prove-m8-execution, task 5)
# --------------------------------------------------------------------------


def test_injected_client_bypasses_sdk_construction_entirely() -> None:
    """Scenario: an injected client bypasses SDK construction entirely.

    ``anthropic`` is unimported first and must stay unimported: checking only
    ``judge.client is sentinel`` would pass even if the constructor built a real
    SDK client and discarded it.
    """
    import sys

    sentinel = object()
    saved = sys.modules.pop("anthropic", None)
    try:
        judge = AnthropicJudge(client=sentinel)
        assert judge.client is sentinel
        assert "anthropic" not in sys.modules, "the SDK was imported despite an injected client"
    finally:
        if saved is not None:
            sys.modules["anthropic"] = saved


def test_injected_client_opens_no_socket() -> None:
    """Construction with an injected client performs zero socket connects."""
    import socket

    with patch.object(socket.socket, "connect", side_effect=AssertionError("egress")) as connect:
        AnthropicJudge(client=object())

    connect.assert_not_called()


def test_absent_injection_preserves_existing_behaviour() -> None:
    """Scenario: absent injection preserves existing behaviour."""
    import inspect

    assert inspect.signature(AnthropicJudge.__init__).parameters["client"].default is None

    with patch("anthropic.Anthropic") as factory:
        judge = AnthropicJudge(api_key="k")

    factory.assert_called_once_with(api_key="k")
    assert judge.client is factory.return_value
