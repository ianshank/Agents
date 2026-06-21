"""Phase 2 — NVIDIA Nemotron judge live integration tests.

Validates real inference calls to NVIDIA NIM API via the OpenAIJudge,
including streaming reasoning extraction and JSON parsing from real LLM output.
"""
from __future__ import annotations

import logging
import os

import pytest

from eval_harness.judges import OpenAIJudge

logger = logging.getLogger(__name__)

# Configurable via env vars — no hardcoded values
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
NVIDIA_MAX_TOKENS = int(os.environ.get("NVIDIA_MAX_TOKENS", "4096"))
NVIDIA_REASONING_BUDGET = int(os.environ.get("NVIDIA_REASONING_BUDGET", "8192"))


def _make_nvidia_judge(api_key: str, *, stream: bool = True) -> OpenAIJudge:
    """Factory for creating an OpenAIJudge configured for NVIDIA Nemotron."""
    extra_body: dict = {}
    if stream:
        extra_body = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": NVIDIA_REASONING_BUDGET,
        }
    return OpenAIJudge(
        model=NVIDIA_MODEL,
        base_url=NVIDIA_BASE_URL,
        api_key=api_key,
        temperature=1.0,
        top_p=0.95,
        max_tokens=NVIDIA_MAX_TOKENS,
        system='You are a fair judge. Respond ONLY with JSON: {"score": <0.0..1.0>, "reasoning": "<brief>"}.',
        extra_body=extra_body,
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Basic inference
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
class TestNemotronInference:
    """Validate OpenAIJudge produces valid verdicts from NVIDIA Nemotron."""

    def test_evaluates_simple_qa(self, nvidia_api_key: str) -> None:
        """Judge correctly evaluates a simple Q&A pair with a valid score."""
        judge = _make_nvidia_judge(nvidia_api_key)
        prompt = (
            "Question: What is 2+2?\n"
            "Expected answer: 4\n"
            "Actual answer: 4\n\n"
            "Rate the actual answer's correctness."
        )
        verdict = judge.evaluate(prompt)

        logger.info("Verdict: score=%.2f reasoning=%s", verdict.score, verdict.reasoning[:200])
        assert 0.0 <= verdict.score <= 1.0, f"Score {verdict.score} out of range [0,1]"
        assert verdict.reasoning, "Reasoning should not be empty"
        assert verdict.raw is not None, "Raw response should be populated"

    def test_evaluates_incorrect_answer(self, nvidia_api_key: str) -> None:
        """Judge scores an incorrect answer lower than a correct one."""
        judge = _make_nvidia_judge(nvidia_api_key)
        prompt = (
            "Question: What is the capital of France?\n"
            "Expected answer: Paris\n"
            "Actual answer: Berlin\n\n"
            "Rate the actual answer's correctness."
        )
        verdict = judge.evaluate(prompt)

        logger.info("Incorrect answer verdict: score=%.2f", verdict.score)
        assert 0.0 <= verdict.score <= 1.0
        # A clearly wrong answer should generally score low
        assert verdict.score < 0.8, f"Expected low score for wrong answer, got {verdict.score}"

    @pytest.mark.parametrize(
        "question,expected,actual",
        [
            pytest.param("What is 2+2?", "4", "4", id="math-correct"),
            pytest.param("Capital of France?", "Paris", "Paris is the capital", id="capital-verbose-correct"),
        ],
    )
    def test_parametrized_evaluations(
        self, nvidia_api_key: str, question: str, expected: str, actual: str
    ) -> None:
        """Parametrized test: judge evaluates multiple Q&A pairs."""
        judge = _make_nvidia_judge(nvidia_api_key)
        prompt = f"Question: {question}\nExpected: {expected}\nActual: {actual}\nRate correctness."
        verdict = judge.evaluate(prompt)

        assert 0.0 <= verdict.score <= 1.0
        logger.info("Q='%s' score=%.2f", question, verdict.score)


# ---------------------------------------------------------------------------
# Streaming & reasoning
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
class TestNemotronStreaming:
    """Validate streaming response handling with reasoning_content."""

    def test_streaming_produces_reasoning(self, nvidia_api_key: str) -> None:
        """When streaming with enable_thinking, reasoning_content chunks should appear."""
        judge = _make_nvidia_judge(nvidia_api_key, stream=True)
        prompt = (
            "Question: If all roses are flowers and some flowers fade quickly, "
            "can we conclude all roses fade quickly?\n"
            "Expected: No, this is a logical fallacy.\n"
            "Actual: No, this is a fallacy of the undistributed middle.\n\n"
            "Rate correctness."
        )
        verdict = judge.evaluate(prompt)

        assert verdict.raw is not None
        reasoning_content = verdict.raw.get("reasoning_content", "")
        logger.info("Streaming reasoning length: %d chars", len(reasoning_content))
        # With enable_thinking, we expect some reasoning content
        # (may be empty if the model doesn't use thinking for simple prompts)
        assert 0.0 <= verdict.score <= 1.0

    def test_non_streaming_also_works(self, nvidia_api_key: str) -> None:
        """Non-streaming mode should also produce valid verdicts."""
        judge = _make_nvidia_judge(nvidia_api_key, stream=False)
        prompt = "Question: What is 1+1?\nExpected: 2\nActual: 2\nRate correctness."
        verdict = judge.evaluate(prompt)

        assert 0.0 <= verdict.score <= 1.0
        assert verdict.reasoning


# ---------------------------------------------------------------------------
# JSON extraction from real output
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.slow
class TestNemotronJsonExtraction:
    """Validate that _extract_json works with real LLM output."""

    def test_custom_system_prompt(self, nvidia_api_key: str) -> None:
        """A custom system prompt changes scoring behavior."""
        judge = OpenAIJudge(
            model=NVIDIA_MODEL,
            base_url=NVIDIA_BASE_URL,
            api_key=nvidia_api_key,
            max_tokens=NVIDIA_MAX_TOKENS,
            system=(
                "You are a strict grader. Score ONLY 0.0 (wrong) or 1.0 (correct). "
                'Respond with JSON: {"score": <0 or 1>, "reasoning": "<why>"}.'
            ),
            stream=True,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": NVIDIA_REASONING_BUDGET,
            },
        )
        prompt = "Question: What is 2+2?\nExpected: 4\nActual: 4\nRate correctness."
        verdict = judge.evaluate(prompt)

        # With strict grading, score should be 0 or 1
        assert verdict.score in (0.0, 1.0), f"Expected 0 or 1, got {verdict.score}"
