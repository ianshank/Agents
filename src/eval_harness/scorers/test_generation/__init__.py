"""Scorers over a generated test suite's execution evidence.

Implements ``openspec/changes/add-testgen-eval-matrix`` task 3. The capability's shape is
one sentence: **the target executes, these read.** ``targets/testgen.py`` runs the suite in
a subprocess sandbox and publishes a payload; every scorer here is a pure function of that
payload and performs no process execution, no filesystem mutation and no network access.

That is the ``state.py`` contract with the producer moved from the engine to the target,
and it buys three properties worth the indirection: the scorers stay deterministic, so
``repetitions > 1`` measures the *target's* variance and not theirs; they stay offline, so
they run in the zero-dependency suite unchanged; and swapping the execution backend later
touches one target rather than four scorers.

**Absent evidence is not a zero.** Each scorer reports ``passed=None`` when the payload is
missing, following ``state.py``. A suite that could not be executed and a suite that killed
no mutants are different outcomes, and collapsing them into ``0.0`` makes an infrastructure
failure indistinguishable from a total agent failure.

**Executability gates the other three.** A mutation score computed over a suite that never
ran is not a low score, it is a meaningless one, so the three quality scorers report
not-applicable for an item whose suite did not collect.
"""

from __future__ import annotations

import logging
from typing import Any

from ...core.types import TESTGEN_EVIDENCE_KEY, ScoreResult, TargetOutput

logger = logging.getLogger(__name__)

#: Comment attached when the payload is absent entirely — no suite-execution target ran, or
#: it failed before producing evidence. Named so a reader of a results file can grep it.
NO_EVIDENCE = "no testgen evidence on the target output"

#: Comment attached when evidence exists but records a suite that never collected. Distinct
#: from :data:`NO_EVIDENCE` on purpose: one is an infrastructure gap, the other is a real
#: measurement of a real suite, and a soak needs to tell them apart.
NOT_EXECUTABLE = "suite was not executable, so this measure is not applicable"

#: Comment attached when a required sub-object of the payload is present but the wrong
#: type. Its own constant rather than :data:`NO_EVIDENCE`: a malformed payload is a bug in
#: whatever produced it, and a soak must be able to tell it from an item nothing ran on.
MALFORMED_EVIDENCE = "testgen evidence is malformed, so this measure is not applicable"


def read_evidence(output: TargetOutput) -> dict[str, Any] | None:
    """The suite-execution payload, or ``None`` when the target published none.

    Type-checked rather than merely present-checked, mirroring ``state.py``'s
    ``isinstance`` guard: a payload of the wrong shape must degrade to not-applicable, not
    raise inside a scorer and abort the run.
    """
    evidence = output.metadata.get(TESTGEN_EVIDENCE_KEY) if output.metadata else None
    return evidence if isinstance(evidence, dict) else None


def read_section(evidence: dict[str, Any], key: str) -> dict[str, Any] | None:
    """A nested mapping from the payload, or ``None`` when it is present but not a mapping.

    :func:`read_evidence` type-checks only the top level, so ``{"mutants": [1, 2, 3]}``
    used to reach ``.get`` on a list and raise ``AttributeError`` **out of the scorer** —
    which, under the default item-error policy (ADR 0038), aborts the entire run. That
    directly contradicts this package's stated contract that a payload of the wrong shape
    degrades rather than raises, so the guard has to hold at every level a scorer indexes.

    A missing key is ``{}`` (the scorers' existing "absent counts are zero" behaviour); a
    key of the wrong type is ``None``, which the caller turns into a not-applicable verdict.
    """
    section = evidence.get(key)
    if section is None:
        return {}
    if not isinstance(section, dict):
        logger.warning("testgen evidence: %r is %s, expected a mapping", key, type(section).__name__)
        return None
    return section


def read_id_list(evidence: dict[str, Any], key: str) -> list[Any] | None:
    """A nested list from the payload, or ``None`` when present but not a list."""
    values = evidence.get(key)
    if values is None:
        return []
    if not isinstance(values, list):
        logger.warning("testgen evidence: %r is %s, expected a list", key, type(values).__name__)
        return None
    return values


def bounded_ratio(numerator: int, denominator: int) -> tuple[float, bool]:
    """``numerator / denominator`` clamped to ``[0, 1]``, plus whether clamping fired.

    Every figure these scorers publish is a *rate*, and ``config/testgen_eval.yaml`` gates
    on the **mean** across items — so a single out-of-range value silently moves the gate
    for every other item in the run. Three such values were reachable before this existed:
    ``killed/covered`` at 2.0 from a real target run, ``failed/ran`` at 3.5, and obligation
    recall at 2.0 from duplicate witnesses.

    The clamp is a floor under a malformed payload, not a substitute for producing a
    well-formed one: each caller emits ``clamped`` into its metadata and logs, so a reader
    of a results file sees an anomaly rather than a plausible number. A zero denominator
    is 0.0 — callers that need "not applicable" instead must test for it themselves,
    because only they know whether a zero denominator means "nothing to measure" or
    "measured nothing".
    """
    if denominator <= 0:
        return 0.0, numerator != 0
    raw = numerator / denominator
    if 0.0 <= raw <= 1.0:
        return raw, False
    clamped = min(1.0, max(0.0, raw))
    logger.warning(
        "testgen: ratio %d/%d = %.3f is outside [0, 1]; reporting %.3f. "
        "The evidence that produced it is internally inconsistent.",
        numerator,
        denominator,
        raw,
        clamped,
    )
    return clamped, True


def is_executable(evidence: dict[str, Any]) -> bool:
    """Whether the suite collected at least one test and raised nothing during collection."""
    return not evidence.get("collection_error") and int(evidence.get("collected") or 0) > 0


def not_applicable(name: str, comment: str, value: float = 0.0) -> ScoreResult:
    """A ``passed=None`` verdict.

    ``value`` still enters the mean — ``EvalEngine._aggregate`` excludes ``None`` verdicts
    from ``pass_rate`` but not from the mean — which is why it is a parameter here and a
    documented knob on each scorer rather than a hidden constant.
    """
    return ScoreResult(name, value=value, passed=None, comment=comment)


def evidence_metadata(evidence: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Carry the counts a verdict rests on onto the score itself.

    Load-bearing rather than decorative: ``TargetOutput.metadata`` is **not** serialised by
    ``RunResult._item_to_dict``, while ``ScoreResult.metadata`` is. Without this, every
    number these scorers computed would be invisible in ``results.json`` and in the HTML
    report, and a soak would have verdicts it could not audit.
    """
    payload: dict[str, Any] = {
        "collected": evidence.get("collected"),
        "timed_out": bool(evidence.get("timed_out")),
    }
    payload.update(extra)
    return payload


# Imported at the bottom for the ``@SCORERS.register`` side effects, mirroring
# ``scorers/__init__.py``'s own tail import of ``state`` and ``trajectory``. Without this
# the classes exist and never register, and the fresh-subprocess registry probe would not
# see them.
from . import execution, mutation  # noqa: E402, F401
