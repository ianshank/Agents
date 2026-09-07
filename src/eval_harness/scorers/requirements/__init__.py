"""Requirements-generation scorers (synthetic scope).

Implements ``openspec/changes/add-requirements-gen-eval-matrix`` task 3: deterministic
scoring of a generated requirement set against the epic's declared gold criteria and the
recorded retrieval evidence. No judge, no numpy, no network — the diversity measure is
lexical by design (the embedding variant belongs behind an optional extra, not here).

**The gold set comes from the corpus, never from the output.** Inferring the target from
the artifact being graded is circular (spec: "The gold set SHALL be carried by the corpus
item").

**The evidence checks read the recorded evidence** (the provenance wrapper's
``REQUIREMENTS_EVIDENCE_KEY`` payload), not the generator's account of what it used.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.types import EvalItem, ScoreResult, TargetOutput

logger = logging.getLogger(__name__)

NO_REQUIREMENTS = "the output carries no requirement set"
NO_GOLD = "the corpus item declares no gold acceptance criteria"
NO_TEMPERATURE = "uninterpretable: no generation temperature recorded"


def not_applicable(name: str, comment: str, value: float = 0.0) -> ScoreResult:
    """A ``passed=None`` verdict (mean still sees ``value``; pass_rate excludes it)."""
    return ScoreResult(name, value=value, passed=None, comment=comment)


def read_requirements(output: TargetOutput) -> list[dict[str, Any]] | None:
    """The generated requirement set from ``output.output``, or None when absent/malformed.

    Accepted shape: a mapping with a ``requirements`` list of mappings. Anything else is
    malformed (None), distinct from an empty set (a real, scorable outcome).
    """
    raw: Any = output.output
    if not isinstance(raw, dict):
        return None
    reqs = raw.get("requirements")
    if reqs is None:
        return None
    if not isinstance(reqs, list) or any(not isinstance(r, dict) for r in reqs):
        logger.warning("requirements: 'requirements' is not a list of mappings")
        return None
    return reqs


def read_gold(item: EvalItem) -> list[str] | None:
    """The declared gold acceptance-criteria ids, or None when undeclared.

    Reads ``expected`` (list of ids) or ``metadata.gold_ac`` (list of {id, text}).
    An empty list is a real (degenerate) gold set; None means the corpus does not
    declare one.
    """
    expected = item.expected
    if isinstance(expected, (list, tuple)):
        return [str(v) for v in expected]
    metadata = item.metadata
    if isinstance(metadata, dict):
        gold = metadata.get("gold_ac")
        if isinstance(gold, list):
            return [str(ac.get("id")) for ac in gold if isinstance(ac, dict) and ac.get("id")]
    return None


def read_recorded_source_ids(output: TargetOutput) -> set[str]:
    """The source_ids the provenance wrapper actually recorded for this run."""
    metadata = output.metadata if isinstance(output.metadata, dict) else {}
    records = metadata.get("requirements_evidence") or []
    return {str(r.get("source_id")) for r in records if isinstance(r, dict) and r.get("source_id")}


def read_declared_tests(item: EvalItem) -> list[str] | None:
    """The tests the corpus declares, or None when it declares none."""
    inputs = item.inputs
    if isinstance(inputs, dict):
        declared = inputs.get("declared_tests")
        if isinstance(declared, list):
            return [str(t) for t in declared]
    return None


def read_contradictions(item: EvalItem) -> list[tuple[str, str]]:
    """Source pairs the task declares as contradictory (a reviewer flag on the inputs)."""
    inputs = item.inputs
    if not isinstance(inputs, dict):
        return []
    raw = inputs.get("contradictions")
    if not isinstance(raw, list):
        return []
    pairs: list[tuple[str, str]] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            pairs.append((str(pair[0]), str(pair[1])))
    return pairs


def read_generation_temperature(output: TargetOutput) -> float | None:
    """The generation temperature recorded with the set, or None (uninterpretable)."""
    raw: Any = output.output
    if isinstance(raw, dict):
        temp = raw.get("generation_temperature")
        if isinstance(temp, (int, float)) and not isinstance(temp, bool):
            return float(temp)
    metadata = output.metadata if isinstance(output.metadata, dict) else {}
    temp = metadata.get("generation_temperature")
    if isinstance(temp, (int, float)) and not isinstance(temp, bool):
        return float(temp)
    return None


# Side-effect registration (mirrors the rca / state / test_generation packages).
from . import diversity, grounding  # noqa: E402, F401
