from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from eval_harness.judges import OpenAIJudge
from eval_harness.langfuse_client import SDKLangfuseClient


@pytest.fixture
def mock_openai():
    with patch("openai.OpenAI") as mock:
        yield mock


def test_openai_judge_initialization(mock_openai):
    judge = OpenAIJudge(
        model="test-model", base_url="http://localhost:1234", api_key="test-key", extra_body={"hello": "world"}
    )
    assert judge.model == "test-model"
    mock_openai.assert_called_once_with(base_url="http://localhost:1234", api_key="test-key")


def test_openai_judge_evaluate_success(mock_openai):
    judge = OpenAIJudge(model="test-model")

    mock_chunk1 = MagicMock()
    mock_chunk1.choices[0].delta.reasoning_content = "thinking... "
    mock_chunk1.choices[0].delta.content = None

    mock_chunk2 = MagicMock()
    mock_chunk2.choices[0].delta.reasoning_content = None
    mock_chunk2.choices[0].delta.content = '{"score": 0.8, "reasoning": "good"}'

    judge.client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2]

    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.8
    assert "thinking..." in verdict.reasoning
    assert "good" in verdict.reasoning


def test_openai_judge_robust_json_parsing(mock_openai):
    judge = OpenAIJudge(model="test-model")

    mock_chunk = MagicMock()
    mock_chunk.choices[0].delta.reasoning_content = None
    mock_chunk.choices[0].delta.content = '```json\n{"score": 0.5, "reasoning": "wrapped"}\n```'

    judge.client.chat.completions.create.return_value = [mock_chunk]

    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.5
    assert verdict.reasoning == "wrapped"


def test_openai_judge_rate_limit_retry(mock_openai):
    import openai

    judge = OpenAIJudge(model="test-model")

    mock_chunk = MagicMock()
    mock_chunk.choices[0].delta.reasoning_content = None
    mock_chunk.choices[0].delta.content = '{"score": 1.0, "reasoning": "finally"}'

    judge.client.chat.completions.create.side_effect = [
        openai.RateLimitError("Rate limit exceeded", response=MagicMock(), body=None),
        [mock_chunk],
    ]

    # Mock sleep so test doesn't actually wait
    with patch("time.sleep"):
        verdict = judge.evaluate("evaluate this")

    assert verdict.score == 1.0
    assert judge.client.chat.completions.create.call_count == 2


def test_openai_judge_retry_attempts_are_configurable(mock_openai):
    import openai

    judge = OpenAIJudge(
        model="test-model",
        retry_attempts=1,
        retry_wait_min_seconds=0.0,
        retry_wait_max_seconds=0.0,
    )
    judge.client.chat.completions.create.side_effect = openai.RateLimitError(
        "Rate limit exceeded", response=MagicMock(), body=None
    )

    with patch("time.sleep"), pytest.raises(openai.RateLimitError):
        judge.evaluate("evaluate this")

    assert judge.client.chat.completions.create.call_count == 1


def test_openai_judge_rejects_invalid_retry_config(mock_openai):
    with pytest.raises(ValueError, match="retry_attempts"):
        OpenAIJudge(model="test-model", retry_attempts=0)
    with pytest.raises(ValueError, match="retry_wait_min_seconds"):
        OpenAIJudge(model="test-model", retry_wait_min_seconds=3.0, retry_wait_max_seconds=2.0)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_tokens": 0}, "max_tokens"),
        ({"top_p": 0.0}, "top_p"),
        ({"failure_score": -0.1}, "failure_score"),
        ({"retry_wait_multiplier_seconds": 0.0}, "retry_wait_multiplier_seconds"),
        ({"retry_wait_max_seconds": -0.1}, "retry_wait_max_seconds"),
        ({"score_field": ""}, "score_field"),
        ({"langfuse_openai_module": ""}, "langfuse_openai_module"),
    ],
)
def test_openai_judge_rejects_invalid_config_values(mock_openai, kwargs, match):
    with pytest.raises(ValueError, match=match):
        OpenAIJudge(model="test-model", **kwargs)


def test_openai_judge_chunk_with_no_choices(mock_openai):
    """Chunk with empty choices list hits the `continue` branch in the streaming loop."""
    judge = OpenAIJudge(model="test-model")

    empty_chunk = MagicMock()
    empty_chunk.choices = []  # falsy → `if not chunk.choices: continue`

    valid_chunk = MagicMock()
    valid_chunk.choices[0].delta.reasoning_content = None
    valid_chunk.choices[0].delta.content = '{"score": 0.7}'

    judge.client.chat.completions.create.return_value = [empty_chunk, valid_chunk]
    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.7


def test_openai_judge_non_streaming_completion(mock_openai):
    judge = OpenAIJudge(model="test-model", stream=False)
    response = types.SimpleNamespace(
        choices=[
            types.SimpleNamespace(
                message=types.SimpleNamespace(
                    content='{"score": 0.6, "reasoning": "non-stream"}',
                    reasoning_content="reasoned ",
                )
            )
        ]
    )
    judge.client.chat.completions.create.return_value = response

    verdict = judge.evaluate("evaluate this")

    assert verdict.score == 0.6
    assert "reasoned" in verdict.reasoning
    assert judge.client.chat.completions.create.call_args.kwargs["stream"] is False


@pytest.mark.parametrize(
    "response",
    [
        types.SimpleNamespace(choices=[]),
        types.SimpleNamespace(choices=[types.SimpleNamespace(message=None)]),
    ],
)
def test_openai_judge_non_streaming_empty_completion_returns_failure(mock_openai, response):
    judge = OpenAIJudge(model="test-model", stream=False, failure_score=0.2)
    judge.client.chat.completions.create.return_value = response

    verdict = judge.evaluate("evaluate this")

    assert verdict.score == 0.2
    assert "Failed to parse" in verdict.reasoning


def test_openai_judge_api_error_propagates(mock_openai):
    """A non-rate-limit error from the API is logged and re-raised."""
    judge = OpenAIJudge(model="test-model")
    judge.client.chat.completions.create.side_effect = RuntimeError("server error")

    with pytest.raises(RuntimeError, match="server error"):
        judge.evaluate("evaluate this")


def test_openai_judge_no_json_returns_default_verdict(mock_openai):
    """Response with no JSON object returns a zero-score default verdict."""
    judge = OpenAIJudge(model="test-model")

    chunk = MagicMock()
    chunk.choices[0].delta.reasoning_content = None
    chunk.choices[0].delta.content = "no braces here"

    judge.client.chat.completions.create.return_value = [chunk]
    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.0
    assert "Failed to parse" in verdict.reasoning


def test_openai_judge_parse_failure_score_is_configurable(mock_openai):
    judge = OpenAIJudge(model="test-model", failure_score=0.25)

    chunk = MagicMock()
    chunk.choices[0].delta.reasoning_content = None
    chunk.choices[0].delta.content = "no braces here"

    judge.client.chat.completions.create.return_value = [chunk]
    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.25


def test_openai_judge_malformed_json_returns_default_verdict(mock_openai):
    """Response with malformed JSON (JSONDecodeError) returns a zero-score default verdict."""
    judge = OpenAIJudge(model="test-model")

    chunk = MagicMock()
    chunk.choices[0].delta.reasoning_content = None
    chunk.choices[0].delta.content = "{not: valid, json}"  # valid regex match, invalid JSON

    judge.client.chat.completions.create.return_value = [chunk]
    verdict = judge.evaluate("evaluate this")
    assert verdict.score == 0.0
    assert "Failed to parse" in verdict.reasoning


def _make_sdk_client() -> object:
    """Instantiate SDKLangfuseClient with a mocked langfuse SDK (no real connection needed)."""
    patcher = patch("langfuse.Langfuse")
    patcher.start()
    client = SDKLangfuseClient()
    patcher.stop()
    return client


def test_openai_judge_attach_client_with_sdk_client(mock_openai):
    """attach_client() with an SDKLangfuseClient switches the client to the Langfuse-traced wrapper."""
    sdk_client = _make_sdk_client()
    judge = OpenAIJudge(model="test-model")

    # Inject a fake langfuse.openai module so the import inside attach_client succeeds.
    mock_lf_openai_cls = MagicMock()
    fake_lf_openai = types.ModuleType("langfuse.openai")
    fake_lf_openai.OpenAI = mock_lf_openai_cls  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"langfuse.openai": fake_lf_openai}):
        judge.attach_client(sdk_client)

    assert mock_lf_openai_cls.called
    assert judge.client is mock_lf_openai_cls.return_value


def test_openai_judge_attach_client_uses_configured_langfuse_module(mock_openai):
    sdk_client = _make_sdk_client()
    judge = OpenAIJudge(model="test-model", langfuse_openai_module="fake_langfuse_openai")

    mock_lf_openai_cls = MagicMock()
    fake_lf_openai = types.ModuleType("fake_langfuse_openai")
    fake_lf_openai.OpenAI = mock_lf_openai_cls  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"fake_langfuse_openai": fake_lf_openai}):
        judge.attach_client(sdk_client)

    assert mock_lf_openai_cls.called


def test_openai_judge_attach_client_langfuse_import_error(mock_openai):
    """If langfuse.openai is unavailable, attach_client() logs a warning and leaves client unchanged."""
    sdk_client = _make_sdk_client()
    judge = OpenAIJudge(model="test-model")
    original_client = judge.client

    with patch.dict("sys.modules", {"langfuse.openai": None}):
        judge.attach_client(sdk_client)  # must not raise

    assert judge.client is original_client
