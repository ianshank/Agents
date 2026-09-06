"""Labeling protocol for human golden-set / audit adjudication.

The protocol is config, not prose: every floor an operator might retune lives on
:class:`LabelingProtocolConfig`. Cohen's kappa is reused from :mod:`agent_core.golden`
rather than re-implemented. This module never invents labels -- it only scores and
adjudicates labels a human already wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .config import ConfigError
from .golden import cohen_kappa, percent_agreement
from .logging_util import debug_span, get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LabelingProtocolConfig:
    """Who labels, how disagreements resolve, and the agreement floor.

    ``min_kappa`` default is Landis-Koch "substantial" (0.60). It is a documented
    field default, not a call-site literal, so an operator can raise it without
    editing adjudication logic.
    """

    n_annotators: int = 2
    min_kappa: float = 0.60
    min_percent_agreement: float = 0.80
    min_pairs: int = 50  # matches CorpusProvenanceConfig.min_items for the first corpus
    tie_policy: str = "escalate"  # "escalate" | "require_third"

    def __post_init__(self) -> None:
        if self.n_annotators < 2:
            raise ConfigError("labeling.n_annotators must be >= 2 (a single annotator cannot kappa)")
        if not 0.0 <= self.min_kappa <= 1.0:
            raise ConfigError("labeling.min_kappa must be in [0, 1]")
        if not 0.0 <= self.min_percent_agreement <= 1.0:
            raise ConfigError("labeling.min_percent_agreement must be in [0, 1]")
        if self.min_pairs < 1:
            raise ConfigError(f"labeling.min_pairs must be >= 1 (got {self.min_pairs!r})")
        if self.tie_policy not in ("escalate", "require_third"):
            raise ConfigError("labeling.tie_policy must be 'escalate' or 'require_third'")


@dataclass(frozen=True)
class Adjudication:
    """Result of combining N annotator labels for one item."""

    label: int | None  # None = escalate; no silent majority-of-one
    reason: str


@dataclass(frozen=True)
class AgreementReport:
    n: int
    percent_agreement: float
    kappa: float
    may_accept: bool
    failing_checks: tuple[str, ...]


def adjudicate(labels: Sequence[int], cfg: LabelingProtocolConfig | None = None) -> Adjudication:
    """Majority vote with an explicit escalate-on-tie. Labels are 0/1 only."""
    conf = cfg or LabelingProtocolConfig()
    if not labels:
        return Adjudication(label=None, reason="no_labels")
    if any(lab not in (0, 1) for lab in labels):
        raise ValueError(f"adjudicate: labels must be 0 or 1, got {labels!r}")
    ones = sum(labels)
    zeros = len(labels) - ones
    if ones == zeros:
        return Adjudication(label=None, reason=f"tie:{conf.tie_policy}")
    if ones > zeros:
        return Adjudication(label=1, reason="majority_positive")
    return Adjudication(label=0, reason="majority_negative")


def agreement_report(
    r1: Sequence[int],
    r2: Sequence[int],
    cfg: LabelingProtocolConfig | None = None,
) -> AgreementReport:
    """Pairwise annotator agreement against the protocol floors."""
    conf = cfg or LabelingProtocolConfig()
    n = len(r1)
    failures: list[str] = []
    with debug_span(logger, "agreement_report", n=n):
        if n < conf.min_pairs:
            failures.append(f"n<{conf.min_pairs}")
        po = percent_agreement(r1, r2)
        kappa = cohen_kappa(r1, r2)
        if po < conf.min_percent_agreement:
            failures.append("percent_agreement")
        if kappa < conf.min_kappa:
            failures.append("kappa")
    may = not failures
    logger.info(
        "labeling agreement n=%d po=%.3f kappa=%.3f may_accept=%s failing=%s",
        n,
        po,
        kappa,
        may,
        failures,
    )
    return AgreementReport(
        n=n,
        percent_agreement=po,
        kappa=kappa,
        may_accept=may,
        failing_checks=tuple(failures),
    )
