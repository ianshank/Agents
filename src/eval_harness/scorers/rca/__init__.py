"""Root-cause diagnosis scorers (synthetic scope).

Implements the ranking half of ``openspec/changes/add-rca-eval-matrix`` tasks 1.1-1.2
and 4.1-4.3: pure, deterministic scorers over a finite candidate set. No judge, no I/O,
no network.

**Shape reuse, not a package dependency.** The prototype fixture copies the
``solution_space`` / ``correct`` shape from ``flow-corpus/data/suites/sdlc.jsonl`` into
``tests/fixtures/rca/`` (F-011: ``flow_protocol`` is the only shared surface with
``flow-corpus/``). Scorers accept either ``solution_space`` (sdlc) or ``candidates``
(future ``corpora/rca/v1``) so the ranking logic can soak before telemetry lands.

**Absent evidence is not a zero.** An unanswerable item (empty correct set) makes
``rca_ac_at_k`` report ``passed=None`` — the ``state.py`` / testgen precedent — so an
infrastructure gap and a wrong diagnosis stay distinguishable.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.types import EvalItem, ScoreResult, TargetOutput

logger = logging.getLogger(__name__)

NO_CANDIDATES = "no declared candidate set on the item"
NO_RANKING = "no ranked diagnosis on the target output"
UNANSWERABLE = "item has no confirmed cause; ranked accuracy is not applicable"
MALFORMED_RANKING = "ranked diagnosis is malformed; this measure is not applicable"

#: Default AC@k cut-offs. Configured on the scorer, never hard-coded into a gate rule.
DEFAULT_KS: tuple[int, ...] = (1, 3, 5)


def not_applicable(name: str, comment: str, value: float = 0.0) -> ScoreResult:
    """A ``passed=None`` verdict (mean still sees ``value``; pass_rate excludes it)."""
    return ScoreResult(name, value=value, passed=None, comment=comment)


def read_candidates(item: EvalItem) -> list[str] | None:
    """Finite candidate-cause set the item declares, or ``None`` when missing/empty.

    Accepts ``inputs.candidates`` (rca corpus) or ``inputs.solution_space`` (sdlc shape),
    then the same keys on ``metadata``. Does **not** invent a singleton from ``correct``.
    """
    for mapping in (item.inputs, item.metadata):
        if not isinstance(mapping, dict):
            continue
        for key in ("candidates", "solution_space"):
            raw = mapping.get(key)
            if raw is None:
                continue
            if not isinstance(raw, (list, tuple)):
                logger.warning("rca: %s is %s, expected a list", key, type(raw).__name__)
                return None
            values = [str(v) for v in raw]
            return values if values else None
    return None


def read_correct(item: EvalItem) -> list[str] | None:
    """Confirmed cause(s). Empty list means unanswerable; ``None`` means undeclared.

    Prefers ``item.expected`` when it is a list/tuple/str; falls back to
    ``inputs.correct`` / ``metadata.correct`` for raw sdlc-shaped fixtures.
    """
    expected = item.expected
    if isinstance(expected, str):
        return [expected]
    if isinstance(expected, (list, tuple)):
        return [str(v) for v in expected]
    if expected is not None:
        logger.warning("rca: expected is %s, expected a list/str", type(expected).__name__)
        return None
    for mapping in (item.inputs, item.metadata):
        if not isinstance(mapping, dict):
            continue
        raw = mapping.get("correct")
        if raw is None:
            continue
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [str(v) for v in raw]
        logger.warning("rca: correct is %s, expected a list/str", type(raw).__name__)
        return None
    return None


def read_ranking(output: TargetOutput) -> list[str] | None:
    """Agent's ranked diagnosis from ``output.output``, or ``None`` when absent/malformed.

    Accepted shapes: a list/tuple of cause ids; a single string; a mapping with
    ``ranked`` / ``ranking`` / ``diagnosis`` key. Declining to answer (``None``, empty
    list, or ``{"abstain": true}``) returns an empty list — distinct from malformed.
    """
    raw: Any = output.output
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, (list, tuple)):
        return [str(v) for v in raw]
    if isinstance(raw, dict):
        if raw.get("abstain") is True or raw.get("insufficient_evidence") is True:
            return []
        for key in ("ranked", "ranking", "diagnosis", "candidates"):
            if key in raw:
                value = raw[key]
                if value is None:
                    return []
                if isinstance(value, str):
                    return [value] if value.strip() else []
                if isinstance(value, (list, tuple)):
                    return [str(v) for v in value]
                logger.warning("rca: output[%r] is %s", key, type(value).__name__)
                return None
        logger.warning("rca: output mapping has no ranked/ranking/diagnosis key")
        return None
    logger.warning("rca: output is %s, expected list/str/mapping", type(raw).__name__)
    return None


def is_unanswerable(correct: list[str]) -> bool:
    """Whether the item declares no confirmed cause."""
    return len(correct) == 0


# Side-effect registration of ranking scorers (mirrors test_generation / state).
from . import ranking  # noqa: E402, F401
