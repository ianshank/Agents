from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest

from eval_harness.judges import BedrockJudge


def _fake_boto3(client: MagicMock) -> types.ModuleType:
    module = types.ModuleType("boto3")
    module.client = MagicMock(return_value=client)  # type: ignore[attr-defined]
    return module


def test_bedrock_judge_uses_configured_request_fields() -> None:
    bedrock_client = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps({"content": [{"text": json.dumps({"quality": 0.7, "reasoning": "grounded"})}]})
    bedrock_client.invoke_model.return_value = {"body": body}
    boto3_module = _fake_boto3(bedrock_client)

    with patch.dict("sys.modules", {"boto3": boto3_module}):
        judge = BedrockJudge(
            model_id="anthropic.test-model",
            region="us-test-1",
            max_tokens=77,
            temperature=0.25,
            system="Return JSON only.",
            score_field="quality",
            anthropic_version="bedrock-test-version",
        )
        verdict = judge.evaluate("score this output")

    boto3_module.client.assert_called_once_with("bedrock-runtime", region_name="us-test-1")  # type: ignore[attr-defined]
    bedrock_client.invoke_model.assert_called_once()
    request = bedrock_client.invoke_model.call_args.kwargs
    payload = json.loads(request["body"])

    assert request["modelId"] == "anthropic.test-model"
    assert payload == {
        "anthropic_version": "bedrock-test-version",
        "max_tokens": 77,
        "temperature": 0.25,
        "system": "Return JSON only.",
        "messages": [{"role": "user", "content": "score this output"}],
    }
    assert verdict.score == 0.7
    assert verdict.reasoning == "grounded"
    assert verdict.raw == {"quality": 0.7, "reasoning": "grounded"}


def test_bedrock_judge_requires_boto3() -> None:
    with patch.dict("sys.modules", {"boto3": None}), pytest.raises(RuntimeError, match="boto3"):
        BedrockJudge(model_id="anthropic.test-model")
