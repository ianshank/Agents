"""Set-diversity scorer: distinct-n plus pairwise token-set Jaccard, pure Python.

The published finding this responds to measured embedding similarity; this repository
keeps numpy off the offline path and a network embedding call cannot run in the offline
suite at all, so the shipped measure is lexical. It is computed **within** one generated
set (no second run required) and the emitted score names what it measured.

**The temperature obligation is load-bearing.** Raising temperature raises diversity, so
a floor is satisfiable by a config knob. A score without its generation temperature is
reported as uninterpretable (``passed=None``), never compared to the floor.
"""

from __future__ import annotations

import logging

from ...core.interfaces import Scorer
from ...core.types import EvalItem, RunContext, ScoreResult, TargetOutput
from ...plugins import SCORERS
from . import NO_REQUIREMENTS, NO_TEMPERATURE, not_applicable, read_generation_temperature, read_requirements

logger = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    """Whitespace/punctuation token set, lowercased. Lexical by design (no embeddings)."""
    return {
        "".join(ch for ch in word if ch.isalnum()) for text_part in [text] for word in text_part.lower().split()
    } - {""}


def _distinct_1(texts: list[str]) -> float:
    """Unique-token ratio over the whole set (distinct-1)."""
    all_tokens = [token for text in texts for token in " ".join(text.lower().split()).split()]
    if not all_tokens:
        return 0.0
    return len(set(all_tokens)) / len(all_tokens)


def _jaccard_diversity(texts: list[str]) -> float:
    """1 - mean pairwise token-set Jaccard over the set's members."""
    sets = [_tokens(text) for text in texts]
    pairs = [(sets[i], sets[j]) for i in range(len(sets)) for j in range(i + 1, len(sets))]
    if not pairs:
        return 0.0
    similarities = []
    for left, right in pairs:
        union = left | right
        similarities.append(len(left & right) / len(union) if union else 0.0)
    return 1.0 - sum(similarities) / len(similarities)


DEFAULT_DIVERSITY_FLOOR: float = 0.35


@SCORERS.register("req_semantic_diversity", aliases=("req-semantic-diversity",))
class ReqSemanticDiversityScorer(Scorer):
    """Within-set diversity: distinct-1 and pairwise Jaccard diversity combined in [0,1].

    The headline ``value`` is the mean of the two components; both are emitted in
    metadata so a reader can see which axis moved. The score carries the generation
    temperature that produced the set; without one it is uninterpretable.
    """

    default_name = "req_semantic_diversity"

    def __init__(self, name: str | None = None, floor: float = DEFAULT_DIVERSITY_FLOOR) -> None:
        super().__init__(name)
        if not 0.0 < floor <= 1.0:
            raise ValueError(f"floor must be in (0, 1], got {floor!r}")
        self.floor = float(floor)

    def score(self, item: EvalItem, output: TargetOutput, ctx: RunContext) -> ScoreResult:
        reqs = read_requirements(output)
        if reqs is None:
            return not_applicable(self.name, NO_REQUIREMENTS)
        texts = [str(req.get("text", "")) for req in reqs]
        texts = [text for text in texts if text.strip()]
        if len(texts) < 2:
            return not_applicable(self.name, "diversity needs at least two non-empty requirements")
        temperature = read_generation_temperature(output)
        if temperature is None:
            logger.debug("Requirement generation temperature missing in output metadata; scoring not applicable")
            return not_applicable(self.name, NO_TEMPERATURE)
        distinct = _distinct_1(texts)
        jaccard = _jaccard_diversity(texts)
        value = (distinct + jaccard) / 2
        return ScoreResult(
            self.name,
            value=value,
            passed=value >= self.floor,
            comment=f"distinct-1={distinct:.3f}, jaccard-diversity={jaccard:.3f} (temperature={temperature})",
            metadata={
                "distinct_1": distinct,
                "jaccard_diversity": jaccard,
                "generation_temperature": temperature,
                "floor": self.floor,
                "measured": "within-set lexical diversity (distinct-1 + pairwise token Jaccard)",
                "requirement_count": len(texts),
            },
        )
