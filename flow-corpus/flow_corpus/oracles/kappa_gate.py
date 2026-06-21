"""Oracle κ-validation: an oracle tier may gate only after agreeing with human audit.

A deterministic oracle can still be *wrong* (a false metamorphic invariant, a buggy
predicate). Before its verdicts are allowed to gate, the tier must agree with a
human-audit sample at Cohen's κ ≥ ``min_oracle_kappa``.

Two corrections baked in vs a naive call to ``cohen_kappa``:

1. **Indeterminates are excluded.** ``OracleResult.verdict`` (and a human label) may
   be ``None``; κ is computed only over *co-determinate* pairs (both sides decided).
   Feeding ``None`` to ``agent_core.golden.cohen_kappa`` would invent a spurious
   third category and distort agreement.
2. **κ-sample power.** κ on a handful of pairs has an enormous CI, so a tier whose
   co-determinate sample is below ``power_min_sample`` is *directional only* and may
   not gate, regardless of the point estimate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.golden import cohen_kappa
from agent_core.logging_util import get_logger

from flow_corpus.config import CorpusConfig
from flow_corpus.validation.power import is_directional_only

_log = get_logger("flow_corpus.oracles.kappa_gate")


@dataclass(frozen=True)
class KappaReport:
    kappa: float | None  # None when no co-determinate pairs exist
    n_codeterminate: int
    n_total: int
    directional_only: bool  # True when below power_min_sample (cannot gate)
    may_gate: bool  # True only if not directional and kappa >= threshold

    @property
    def passes(self) -> bool:
        return self.may_gate


def validate_oracle(
    oracle_verdicts: Sequence[bool | None],
    human_verdicts: Sequence[bool | None],
    cfg: CorpusConfig,
) -> KappaReport:
    """Validate an oracle tier against a paired human-audit sample.

    Args:
        oracle_verdicts: the tier's verdicts on the audited instances.
        human_verdicts: the authoritative human labels for the same instances (aligned).
    """
    if len(oracle_verdicts) != len(human_verdicts):
        raise ValueError("oracle_verdicts and human_verdicts must be aligned (equal length)")

    pairs = [
        (int(o), int(h))
        for o, h in zip(oracle_verdicts, human_verdicts, strict=True)
        if o is not None and h is not None
    ]
    n_co = len(pairs)

    if n_co == 0:
        return KappaReport(
            kappa=None,
            n_codeterminate=0,
            n_total=len(oracle_verdicts),
            directional_only=True,
            may_gate=False,
        )

    kappa = cohen_kappa([o for o, _ in pairs], [h for _, h in pairs])
    directional = is_directional_only(n_co, cfg.power_min_sample)
    may_gate = (not directional) and kappa >= cfg.min_oracle_kappa
    _log.debug(
        "oracle kappa-validation kappa=%.4f n_codeterminate=%d n_total=%d "
        "directional_only=%s may_gate=%s",
        kappa,
        n_co,
        len(oracle_verdicts),
        directional,
        may_gate,
    )
    return KappaReport(
        kappa=kappa,
        n_codeterminate=n_co,
        n_total=len(oracle_verdicts),
        directional_only=directional,
        may_gate=may_gate,
    )
