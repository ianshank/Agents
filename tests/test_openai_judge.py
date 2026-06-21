from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from eval_harness.judges import OpenAIJudge


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
    with patch("langfuse.Langfuse"):
        from eval_harness.langfuse_client import SDKLangfuseClient

        return SDKLangfuseClient()


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


def test_openai_judge_attach_client_langfuse_import_error(mock_openai):
    """If langfuse.openai is unavailable, attach_client() logs a warning and leaves client unchanged."""
    sdk_client = _make_sdk_client()
    judge = OpenAIJudge(model="test-model")
    original_client = judge.client

    with patch.dict("sys.modules", {"langfuse.openai": None}):
        judge.attach_client(sdk_client)  # must not raise

    assert judge.client is original_client


def test_openai_judge_validation_errors(mock_openai):
    with pytest.raises(ValueError, match="max_tokens must be >= 1"):
        OpenAIJudge(model="test", max_tokens=0)

    with pytest.raises(ValueError, match="temperature must be >= 0"):
        OpenAIJudge(model="test", temperature=-0.5)

    with pytest.raises(ValueError, match="top_p must be > 0"):
        OpenAIJudge(model="test", top_p=0.0)

    with pytest.raises(ValueError, match="failure_score must be >= 0"):
        OpenAIJudge(model="test", failure_score=-1.0)

    with pytest.raises(ValueError, match="retry_attempts must be >= 1"):
        OpenAIJudge(model="test", retry_attempts=0)

    with pytest.raises(ValueError, match="retry_wait_multiplier_seconds must be > 0"):
        OpenAIJudge(model="test", retry_wait_multiplier_seconds=-1.0)

    with pytest.raises(ValueError, match="retry_wait_min_seconds must be >= 0"):
        OpenAIJudge(model="test", retry_wait_min_seconds=-1.0)

    with pytest.raises(ValueError, match="retry_wait_max_seconds must be >= 0"):
        OpenAIJudge(model="test", retry_wait_max_seconds=-1.0)

    with pytest.raises(ValueError, match="retry_wait_min_seconds must be <= retry_wait_max_seconds"):
        OpenAIJudge(model="test", retry_wait_min_seconds=5.0, retry_wait_max_seconds=2.0)

    with pytest.raises(ValueError, match="score_field must not be empty"):
        OpenAIJudge(model="test", score_field="")

    with pytest.raises(ValueError, match="langfuse_openai_module must not be empty"):
        OpenAIJudge(model="test", langfuse_openai_module="")


def test_openai_judge_non_streaming(mock_openai):
    judge = OpenAIJudge(model="test-model", stream=False)

    mock_message = MagicMock()
    mock_message.content = '{"score": 0.9, "reasoning": "great job"}'
    mock_message.reasoning_content = "thinking non-stream"

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    judge.client.chat.completions.create.return_value = mock_completion

    verdict = judge.evaluate("test non-stream")
    assert verdict.score == 0.9
    assert "thinking non-stream" in verdict.reasoning
    assert "great job" in verdict.reasoning


def test_collect_completion_message_edges(mock_openai):
    judge = OpenAIJudge(model="test-model", stream=False)

    # 1. No choices
    mock_completion = MagicMock()
    mock_completion.choices = []
    content, reasoning = judge._collect_completion_message(mock_completion)
    assert content == "" and reasoning == ""

    # 2. Choice message is None
    mock_choice = MagicMock()
    mock_choice.message = None
    mock_completion.choices = [mock_choice]
    content, reasoning = judge._collect_completion_message(mock_completion)
    assert content == "" and reasoning == ""
