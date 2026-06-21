"""Oracle validation: measure the judge before it gates a launch.

An unvalidated judge is *advisory, not a gate*. We measure the judge's verdicts against
a human-label set via Cohen's κ and a statistical-power floor, reusing
``flow_corpus.oracles.kappa_gate.validate_oracle`` (which excludes indeterminate pairs
and power-gates via ``is_directional_only``). The judge may gate only when it both
clears ``min_judge_kappa`` and has enough co-determinate pairs to be non-directional.
"""

from __future__ import annotations

from collections.abc import Sequence

from flow_corpus.oracles.kappa_gate import KappaReport, validate_oracle

from .config import BRConfig
from .judge import JVerdict


def validate_judge(
    verdicts: Sequence[JVerdict],
    human_labels: Sequence[bool | None],
    cfg: BRConfig,
) -> KappaReport:
    """Validate the judge's verdicts against an aligned human-label set.

    Indeterminate verdicts/labels (``None``) are dropped before κ is computed; below
    ``power_min_sample`` co-determinate pairs the result is directional-only and cannot
    gate. Returns a :class:`KappaReport` whose ``may_gate`` is the trust signal the
    detector and gate consume.
    """
    if len(verdicts) != len(human_labels):
        raise ValueError("verdicts and human_labels must be aligned (equal length)")
    judge_verdicts: list[bool | None] = [v.label for v in verdicts]
    return validate_oracle(judge_verdicts, list(human_labels), cfg.as_corpus_config())
