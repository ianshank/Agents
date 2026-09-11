"""LLM-as-judge over Amazon Bedrock."""

from __future__ import annotations

import json
from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES


@JUDGES.register("bedrock")
class BedrockJudge(Judge):  # pragma: no cover - requires boto3 + network
    """LLM-as-judge over Amazon Bedrock. Model id and region come from config."""

    def __init__(
        self,
        model_id: str,
        region: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
        system: str | None = None,
        score_field: str = "score",
    ):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "BedrockJudge requires boto3. Install with: pip install 'langfuse-eval-harness[bedrock]'"
            ) from exc
        self._client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system = system or 'Respond ONLY with JSON: {"score": <0..1>, "reasoning": <str>}.'
        self.score_field = score_field

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": self.system,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = self._client.invoke_model(modelId=self.model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        text = payload["content"][0]["text"]
        parsed = json.loads(text)
        return JudgeVerdict(
            score=float(parsed[self.score_field]),
            reasoning=str(parsed.get("reasoning", "")),
            raw=parsed,
        )
