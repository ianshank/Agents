"""Run-level reliability diagnostics, split out of ``engine.py`` (F-060 prerequisite).

Extracted verbatim (behavior-preserving, no logic change) to free headroom under
the 500-line size budget ahead of ``add-stateful-outcome-evaluation``'s engine
lifecycle changes. Pure — depends only on result data and two facts the engine
has already resolved, not on ``EvalEngine``/config/target directly, so it is
trivially unit-testable on its own.
"""

from __future__ import annotations

from .types import ItemResult, ScoreResult


def _reliability_diagnostics(
    results: list[ItemResult],
    *,
    repetitions: int,
    declared_deterministic: bool | None,
) -> list[dict[str, str]]:
    """Detect the ADR 0029 vacuous-pass case: every attempt of some item
    passed (``pass^k == 1.0``) only because sampling is deterministic, not
    because the target is reliable.

    Deliberately local and minimal, not a call into ``ReliabilityAggregator``
    (``reliability.py``): this needs one boolean per item to decide whether a
    single run-level caveat applies. ``ReliabilityAggregator`` computes the
    richer, standalone per-item ``pass^k``/distributions separately; some
    overlap between the two is expected and acceptable — they serve different
    consumers.

    Detection is (1) declared, via ``declared_deterministic`` when the target
    states one; (2) observed, when unknown (``None``), by checking whether
    every attempt of that item returned an equal ``TargetOutput.output``.
    Returns at most one diagnostic — the message carries no per-item detail,
    so repeating it per affected item would add no information.
    """
    if repetitions <= 1:
        return []

    # Past the guard above, every result in this run came from the
    # repetitions>1 loops, so attempt_index is always set — no filter needed.
    by_item: dict[str, list[ItemResult]] = {}
    for ir in results:
        by_item.setdefault(ir.item.id, []).append(ir)

    for attempts in by_item.values():
        by_scorer: dict[str, list[ScoreResult]] = {}
        for ir in attempts:
            for s in ir.scores:
                if s.passed is not None:
                    by_scorer.setdefault(s.name, []).append(s)

        item_pass_power_k = any(
            len(scores) == len(attempts) and all(s.passed for s in scores) for scores in by_scorer.values()
        )
        if not item_pass_power_k:
            continue

        is_deterministic = declared_deterministic
        if is_deterministic is None:
            first_output = attempts[0].output.output
            is_deterministic = all(ir.output.output == first_output for ir in attempts[1:])
        if is_deterministic:
            return [
                {
                    "code": "deterministic_sampling",
                    "message": (
                        "pass^k is 1.0 because sampling is deterministic, not because the agent is reliable."
                    ),
                }
            ]

    return []
