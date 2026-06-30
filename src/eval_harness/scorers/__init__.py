"""Built-in scorers. Each registers under a stable name (plus aliases)."""

from __future__ import annotations

import json
import re
from typing import Any

from ..core._serialize import as_text as _as_text
from ..core.interfaces import Scorer
from ..core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ..plugins import SCORERS


@SCORERS.register("exact_match", aliases=("exact",))
class ExactMatchScorer(Scorer):
    default_name = "exact_match"

    def __init__(self, name: str | None = None, case_sensitive: bool = True, strip: bool = True):
        super().__init__(name)
        self.case_sensitive = case_sensitive
        self.strip = strip

    def _norm(self, value: Any) -> str:
        text = _as_text(value)
        if self.strip:
            text = text.strip()
        if not self.case_sensitive:
            text = text.lower()
        return text

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        match = self._norm(output.output) == self._norm(item.expected)
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match)


@SCORERS.register("regex_match", aliases=("regex",))
class RegexMatchScorer(Scorer):
    default_name = "regex_match"

    def __init__(self, name: str | None = None, pattern: str = ".*", flags: int = 0):
        super().__init__(name)
        self.pattern = re.compile(pattern, flags)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        match = bool(self.pattern.search(_as_text(output.output)))
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match)


@SCORERS.register("contains")
class ContainsScorer(Scorer):
    default_name = "contains"

    def __init__(self, name: str | None = None, substring: str = "", case_sensitive: bool = False):
        super().__init__(name)
        self.substring = substring
        self.case_sensitive = case_sensitive

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        haystack = _as_text(output.output)
        needle = self.substring
        if not self.case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        match = needle in haystack
        return ScoreResult(self.name, value=1.0 if match else 0.0, passed=match)


@SCORERS.register("json_keys", aliases=("schema_keys",))
class JsonKeysScorer(Scorer):
    """Fraction of required keys present in a JSON/dict output."""

    default_name = "json_keys"

    def __init__(self, name: str | None = None, required: list[str] | None = None):
        super().__init__(name)
        self.required = required or []

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        data = output.output
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return ScoreResult(self.name, value=0.0, passed=False, comment="output is not valid JSON")
        if not isinstance(data, dict):
            return ScoreResult(self.name, value=0.0, passed=False, comment="output is not an object")
        if not self.required:
            return ScoreResult(self.name, value=1.0, passed=True)
        present = sum(1 for k in self.required if k in data)
        value = present / len(self.required)
        missing = [k for k in self.required if k not in data]
        return ScoreResult(
            self.name,
            value=value,
            passed=value == 1.0,
            comment=None if not missing else f"missing keys: {missing}",
        )


@SCORERS.register("weighted", aliases=("composite", "ensemble"))
class CompositeScorer(Scorer):
    """Combines several child scorers into one weighted composite score.

    Each ``components`` entry is ``{type, params?, weight?, name?}``. Children are
    built once at construction via the same registry the engine uses, so an
    ``llm_judge`` child still receives ``ctx.judge`` when scored. The composite
    value is the weight-normalised mean of child values
    (``Σ wᵢ·vᵢ / Σ wᵢ``); the per-child breakdown is recorded in
    ``ScoreResult.metadata['components']``. Nothing is hardcoded — weights and the
    optional ``pass_threshold`` come from config; omitted weights default to 1.0.
    """

    default_name = "weighted"

    _STRATEGIES = ("weighted_mean",)

    def __init__(
        self,
        name: str | None = None,
        components: list[dict] | None = None,
        strategy: str = "weighted_mean",
        pass_threshold: float | None = None,
    ):
        super().__init__(name)
        if strategy not in self._STRATEGIES:
            raise ValueError(f"unknown strategy {strategy!r}; supported: {list(self._STRATEGIES)}")
        self.strategy = strategy
        self.pass_threshold = None if pass_threshold is None else float(pass_threshold)
        specs = components or []
        if not specs:
            raise ValueError("CompositeScorer requires at least one component")
        # Build children once; record the resolved label and weight alongside.
        self._children: list[tuple[str, float, Scorer]] = []
        for spec in specs:
            if not isinstance(spec, dict):
                raise ValueError(f"each CompositeScorer component must be a mapping; got {type(spec).__name__}")
            ctype = spec.get("type")
            if not ctype:
                raise ValueError("each CompositeScorer component must specify a 'type'")
            child = SCORERS.create(ctype, spec.get("params", {}))
            label = spec.get("name") or child.name
            weight = float(spec.get("weight", 1.0))
            if weight < 0:
                raise ValueError(f"component weight must be >= 0; got {weight} for {label!r}")
            self._children.append((label, weight, child))
        if sum(w for _, w, _ in self._children) <= 0:
            raise ValueError("CompositeScorer total weight must be > 0")

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        breakdown: list[dict[str, Any]] = []
        weighted_sum = 0.0
        total_weight = 0.0
        child_passed: list[bool | None] = []
        for label, weight, child in self._children:
            res = child.score(item, output, ctx)
            weighted_sum += weight * res.value
            total_weight += weight
            child_passed.append(res.passed)
            breakdown.append({"name": label, "value": res.value, "weight": weight, "passed": res.passed})
        value = weighted_sum / total_weight  # total_weight > 0 guaranteed in __init__
        if self.pass_threshold is not None:
            passed: bool | None = value >= self.pass_threshold
        else:
            # No explicit threshold: composite passes only if every child that
            # reported a pass/fail verdict passed (None verdicts are ignored).
            verdicts = [p for p in child_passed if p is not None]
            passed = all(verdicts) if verdicts else None
        return ScoreResult(
            self.name,
            value=value,
            passed=passed,
            metadata={"strategy": self.strategy, "components": breakdown},
        )


@SCORERS.register("llm_judge", aliases=("llm-judge", "judge"))
class LLMJudgeScorer(Scorer):
    """Delegates qualitative scoring to the injected judge."""

    default_name = "llm_judge"

    DEFAULT_TEMPLATE = (
        "You are grading an AI response.\n"
        "Input: {input}\n"
        "Expected: {expected}\n"
        "Response: {output}\n"
        "Return a quality score in [0,1]."
    )

    def __init__(
        self,
        name: str | None = None,
        prompt_template: str | None = None,
        threshold: float = 0.5,
    ):
        super().__init__(name)
        self.prompt_template = prompt_template or self.DEFAULT_TEMPLATE
        self.threshold = float(threshold)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        if ctx.judge is None:
            raise RuntimeError(f"scorer '{self.name}' requires a judge but none was configured")
        prompt = self.prompt_template.format(input=item.inputs, expected=item.expected, output=output.output)
        verdict = ctx.judge.evaluate(prompt, context={"item_id": item.id})
        return ScoreResult(
            self.name,
            value=verdict.score,
            passed=verdict.score >= self.threshold,
            comment=verdict.reasoning or None,
        )
