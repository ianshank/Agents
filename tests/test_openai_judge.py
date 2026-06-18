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
