from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest

# Create clean mock boto3 module and client
mock_boto3 = MagicMock()
mock_client = MagicMock()
mock_boto3.client.return_value = mock_client


@pytest.fixture(autouse=True)
def setup_boto3(monkeypatch):
    mock_boto3.client.reset_mock()
    mock_client.invoke_model.reset_mock()
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)
    yield


def test_bedrock_judge_successful_evaluation():
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps(
        {"content": [{"text": '{"score": 0.85, "reasoning": "great answer"}'}]}
    ).encode("utf-8")

    mock_client.invoke_model.return_value = {"body": mock_payload}

    from eval_harness.judges import BedrockJudge

    judge = BedrockJudge(model_id="anthropic.claude-v2")
    mock_boto3.client.assert_called_once_with("bedrock-runtime", region_name=None)

    verdict = judge.evaluate("my prompt")
    assert verdict.score == 0.85
    assert verdict.reasoning == "great answer"
    assert verdict.raw == {"score": 0.85, "reasoning": "great answer"}


def test_bedrock_judge_missing_optional_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)

    from eval_harness.judges import BedrockJudge

    with pytest.raises(RuntimeError, match="BedrockJudge requires boto3"):
        BedrockJudge(model_id="anthropic.claude-v2")


def test_bedrock_judge_missing_score_field():
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps({"content": [{"text": '{"reasoning": "missing score key"}'}]}).encode(
        "utf-8"
    )
    mock_client.invoke_model.return_value = {"body": mock_payload}

    from eval_harness.judges import BedrockJudge

    judge = BedrockJudge(model_id="anthropic.claude-v2")
    verdict = judge.evaluate("my prompt")
    assert verdict.score == 0.0
    assert verdict.reasoning == "missing score key"


def test_bedrock_judge_malformed_json():
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps({"content": [{"text": "not valid json"}]}).encode("utf-8")
    mock_client.invoke_model.return_value = {"body": mock_payload}

    from eval_harness.judges import BedrockJudge

    judge = BedrockJudge(model_id="anthropic.claude-v2")
    verdict = judge.evaluate("my prompt")
    assert verdict.score == 0.0
    assert "Failed to parse Bedrock output" in verdict.reasoning
