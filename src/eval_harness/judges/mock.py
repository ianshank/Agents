"""Deterministic offline judge driven entirely by config."""

from __future__ import annotations

from typing import Any

from ..core.interfaces import Judge
from ..core.types import JudgeVerdict
from ..plugins import JUDGES


@JUDGES.register("mock", aliases=("deterministic",))
class MockJudge(Judge):
    """Deterministic judge driven entirely by config.

    ``rules`` is a list of ``{contains: str, score: float}``; the first rule whose
    substring is found in the prompt wins, else ``default_score`` is returned.
    """

    def __init__(self, default_score: float = 1.0, rules: list[dict[str, Any]] | None = None):
        self.default_score = float(default_score)
        self.rules = rules or []

    def evaluate(self, prompt: str, context: dict[str, Any] | None = None) -> JudgeVerdict:
        for rule in self.rules:
            needle = rule.get("contains", "")
            if needle and needle in prompt:
                score = float(rule["score"])
                return JudgeVerdict(score=score, reasoning=f"matched rule {needle!r}")
        return JudgeVerdict(score=self.default_score, reasoning="default")
