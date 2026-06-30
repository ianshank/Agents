"""Offline tests for the real model-backed ``ModelTarget`` (F-027).

No network and no real SDK client is constructed: every test injects a stub
``client`` through the dependency-injection seam, exactly mirroring the
stub-client style of ``tests/test_openai_judge.py`` and
``tests/test_anthropic_judge.py``. Only the bare SDK-construction lines in
``ModelTarget._build_*`` carry ``# pragma: no cover``; all prompt/parse/latency/
error logic is exercised here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eval_harness.core.types import EvalItem
from eval_harness.plugins import TARGETS, bootstrap
from eval_harness.targets.model import ModelTarget

_ITEM = EvalItem(id="1", inputs={"prompt": "hello"})


def _openai_chunk(content: str | None) -> MagicMock:
    chunk = MagicMock()
    chunk.choices[0].delta.content = content
    return chunk


def _openai_client(chunks: list) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = chunks
    return client


# --------------------------------------------------------------------- registry
def test_registered_in_targets_registry():
    bootstrap()
    assert "model" in TARGETS.names()
    assert "llm" in TARGETS  # alias resolves via __contains__


def test_create_via_registry_returns_target_runner():
    bootstrap()
    target = TARGETS.create("model", {"provider": "openai", "model": "m", "client": _openai_client([])})
    assert isinstance(target, ModelTarget)


def test_invalid_provider_raises():
    with pytest.raises(ValueError, match="provider must be one of"):
        ModelTarget(provider="nope", model="m", client=MagicMock())


# ----------------------------------------------------------------------- openai
def test_openai_returns_joined_content_with_latency_and_metadata():
    client = _openai_client([_openai_chunk("hel"), _openai_chunk("lo")])
    target = ModelTarget(provider="openai", model="gpt-x", client=client)

    out = target.run(_ITEM)

    assert out.output == "hello"
    assert out.error is None
    assert out.latency_ms is not None
    assert out.metadata == {"provider": "openai", "model": "gpt-x"}


def test_openai_skips_chunks_with_no_choices():
    empty = MagicMock()
    empty.choices = []  # falsy → `continue`
    client = _openai_client([empty, _openai_chunk("ok")])
    target = ModelTarget(provider="openai", model="m", client=client)

    assert target.run(_ITEM).output == "ok"


def test_openai_skips_none_content_delta():
    # A chunk whose delta.content is None (e.g. a reasoning-only delta) is skipped.
    client = _openai_client([_openai_chunk(None), _openai_chunk("kept")])
    target = ModelTarget(provider="openai", model="m", client=client)

    assert target.run(_ITEM).output == "kept"


def test_openai_passes_system_and_sampling_params():
    client = _openai_client([_openai_chunk("x")])
    target = ModelTarget(
        provider="openai",
        model="m",
        system="be terse",
        temperature=0.3,
        top_p=0.9,
        max_tokens=42,
        extra_body={"k": "v"},
        client=client,
    )
    target.run(_ITEM)

    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["messages"][0] == {"role": "system", "content": "be terse"}
    assert kwargs["messages"][1] == {"role": "user", "content": "hello"}
    assert kwargs["temperature"] == 0.3
    assert kwargs["top_p"] == 0.9
    assert kwargs["max_tokens"] == 42
    assert kwargs["extra_body"] == {"k": "v"}
    assert kwargs["stream"] is True


def test_openai_retries_on_rate_limit_then_succeeds():
    import openai

    client = MagicMock()
    client.chat.completions.create.side_effect = [
        openai.RateLimitError("slow down", response=MagicMock(), body=None),
        [_openai_chunk("done")],
    ]
    target = ModelTarget(provider="openai", model="m", retry_min_seconds=0, retry_max_seconds=0, client=client)

    with patch("time.sleep"):  # don't actually wait between retries
        out = target.run(_ITEM)

    assert out.output == "done"
    assert client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------- bedrock
def _bedrock_client(text: str) -> MagicMock:
    import json

    client = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps({"content": [{"text": text}]})
    client.invoke_model.return_value = {"body": body}
    return client


def test_bedrock_returns_first_text_block():
    client = _bedrock_client("bedrock says hi")
    target = ModelTarget(provider="bedrock", model="anthropic.claude", region="us-east-1", client=client)

    out = target.run(_ITEM)

    assert out.output == "bedrock says hi"
    assert out.metadata["provider"] == "bedrock"
    _, kwargs = client.invoke_model.call_args
    assert kwargs["modelId"] == "anthropic.claude"


def test_bedrock_omits_temperature_when_none():
    import json

    client = _bedrock_client("x")
    target = ModelTarget(provider="bedrock", model="m", temperature=None, client=client)
    target.run(_ITEM)

    sent = json.loads(client.invoke_model.call_args.kwargs["body"])
    assert "temperature" not in sent


def test_bedrock_includes_system_when_set():
    import json

    client = _bedrock_client("x")
    ModelTarget(provider="bedrock", model="m", system="be brief", client=client).run(_ITEM)

    sent = json.loads(client.invoke_model.call_args.kwargs["body"])
    assert sent["system"] == "be brief"


# -------------------------------------------------------------------- anthropic
def _anthropic_client(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create.return_value = resp
    return client


def test_anthropic_joins_text_blocks():
    client = _anthropic_client("claude reply")
    target = ModelTarget(provider="anthropic", model="claude-opus-4-8", client=client)

    out = target.run(_ITEM)

    assert out.output == "claude reply"
    assert out.metadata["model"] == "claude-opus-4-8"


def test_anthropic_includes_system_when_set():
    client = _anthropic_client("ok")
    ModelTarget(provider="anthropic", model="m", system="be brief", client=client).run(_ITEM)

    assert client.messages.create.call_args.kwargs["system"] == "be brief"


def test_anthropic_omits_temperature_by_default_but_sends_when_set():
    client = _anthropic_client("x")
    # Default temperature is 0.0 → still sent (only None omits).
    ModelTarget(provider="anthropic", model="m", temperature=None, client=client).run(_ITEM)
    assert "temperature" not in client.messages.create.call_args.kwargs

    client2 = _anthropic_client("x")
    ModelTarget(provider="anthropic", model="m", temperature=0.5, client=client2).run(_ITEM)
    assert client2.messages.create.call_args.kwargs["temperature"] == 0.5


# ------------------------------------------------------------------- prompt/err
def test_prompt_template_formats_from_item_inputs():
    client = _anthropic_client("ok")
    target = ModelTarget(provider="anthropic", model="m", prompt_template="Q: {q}\nContext: {ctx}", client=client)
    target.run(EvalItem(id="2", inputs={"q": "why", "ctx": "because"}))

    sent_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert sent_prompt == "Q: why\nContext: because"


def test_model_failure_is_surfaced_as_scored_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    target = ModelTarget(provider="openai", model="m", client=client)

    out = target.run(_ITEM)

    assert out.output is None
    assert out.error == "boom"
    assert out.latency_ms is not None


def test_missing_prompt_template_key_is_surfaced_as_error():
    client = _anthropic_client("ok")
    target = ModelTarget(provider="anthropic", model="m", prompt_template="{missing}", client=client)

    out = target.run(EvalItem(id="3", inputs={"prompt": "x"}))

    assert out.output is None
    assert out.error is not None  # KeyError surfaced, not raised
