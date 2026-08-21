"""Panel-member calibration: how much do a ``PanelJudge``'s members actually agree?

Split from ``agent_core_adapter/__init__.py`` purely to stay under the 500-line
file budget (the same reason ``scorers/__init__.py`` keeps ``trajectory.py`` and
``judges/__init__.py`` keeps ``panel.py`` as sibling modules) -- re-exported from
``__init__.py`` since, unlike those two, there is no registry decorator here to
trigger via a bottom-of-file side-effect import; this is an ordinary function.

``PanelJudge.evaluate``'s own ``raw["spread"]``/``raw["stdev"]`` describe
disagreement *within one call*. Kappa answers a different, longer-horizon
question: across a whole calibration corpus, do two members' pass/fail calls
track each other beyond chance, or is one of them noise? A panel whose members
score in lock-step (kappa near 1) is not diversifying anything; a panel whose
members barely agree (kappa near 0, or negative) is not a considered-consensus
mechanism either -- both are findings a human calibrating a panel needs to see,
not just the per-item spread.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def pairwise_member_kappa(
    per_item_member_scores: Mapping[str, Sequence[float]],
    *,
    threshold: float = 0.5,
) -> tuple[tuple[str, str, float], ...]:
    """Cohen's kappa between every pair of panel members' pass/fail decisions.

    ``per_item_member_scores`` maps each member's label (``PanelJudge``'s own
    ``raw["members"][i]["name"]``) to its score on each item in a corpus, in the
    same item order for every member -- the shape a caller accumulates by running
    a panel across a calibration corpus and collecting ``verdict.raw["members"]``
    per item. Scores are binarized at ``threshold`` (mirrors
    ``PanelJudge.member_pass_threshold``'s own default) before being handed to
    :func:`agent_core.golden.cohen_kappa`, since kappa is defined over categorical
    labels, not continuous scores -- computing it directly on raw scores would
    silently produce a number that answers a different question.

    Returns one ``(member_a, member_b, kappa)`` row per unordered member pair,
    member names sorted for a deterministic, diff-friendly result.
    """
    from agent_core.golden import cohen_kappa

    names = sorted(per_item_member_scores)
    if len(names) < 2:
        raise ValueError("pairwise_member_kappa requires at least two members")
    lengths = {len(per_item_member_scores[name]) for name in names}
    if len(lengths) > 1:
        raise ValueError("pairwise_member_kappa requires every member to have the same number of items")
    if lengths == {0}:
        raise ValueError("pairwise_member_kappa requires at least one item")

    labels = {name: [1 if score >= threshold else 0 for score in per_item_member_scores[name]] for name in names}

    rows: list[tuple[str, str, float]] = []
    for i, member_a in enumerate(names):
        for member_b in names[i + 1 :]:
            rows.append((member_a, member_b, cohen_kappa(labels[member_a], labels[member_b])))
    return tuple(rows)
