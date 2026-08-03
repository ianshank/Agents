"""Dataset assembly for proxy-correlation measurement.

Joins proxy values from extractors with authoritative labels from the outcome store
to create labeled and unlabeled proxy datasets for analysis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .domains import DOMAIN_FILTERS, in_domain_scope
from .logging_util import get_logger
from .outcome_store import LabelSource, OutcomeRecord, OutcomeStore
from .proxies import ProxyExtractor

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProxyPair:
    """A labeled (change_id, proxy, correctness) triple."""

    change_id: str
    domain: str
    proxy: float
    correct: bool


@dataclass(frozen=True)
class ProxyDataset:
    """Labeled pairs plus the unlabeled proxy pool PPI borrows strength from."""

    proxy: str
    labeled: tuple[ProxyPair, ...]
    unlabeled: tuple[float, ...]


def _records_by_change(store: OutcomeStore) -> dict[str, list[OutcomeRecord]]:
    """Group all records in the store by change_id."""
    grouped: dict[str, list[OutcomeRecord]] = {}
    for r in store.all():
        grouped.setdefault(r.change_id, []).append(r)
    return grouped


def build_dataset(
    store: OutcomeStore,
    extractor: ProxyExtractor,
    *,
    domain_filter: str = "all",
) -> ProxyDataset:
    """Join each change's proxy value to its authoritative label, if it has one.

    The join is by ``change_id`` across append-only records, because a single record
    carries one label from one source: the mechanical signal and the human verdict are
    *different rows*. Changes with a HUMAN_AUDIT row become labelled pairs; the rest
    contribute their proxy value to the unlabelled pool.

    Args:
        store: Outcome store with audit records
        extractor: Proxy value extractor
        domain_filter: Domain filter ("all", "agent", "human")

    Returns:
        ProxyDataset with labeled pairs and unlabeled proxy values
    """
    labeled: list[ProxyPair] = []
    unlabeled: list[float] = []
    # `resolved()` owns the authoritative-label precedence (HUMAN_AUDIT wins, later
    # verdict supersedes). Re-deriving it here by scanning for the *first* audit row got a
    # different answer whenever an early audit row carried `label=None`, silently demoting
    # an audited change into the unlabelled pool -- losing a scarce label and breaking the
    # disjointness the variance formula assumes. The grouping below is still needed
    # because a proxy may read rows `resolved()` collapses away.
    resolved = store.resolved()
    for change_id, records in sorted(_records_by_change(store).items()):
        authoritative = resolved.get(change_id)
        domain = authoritative.domain if authoritative is not None else records[0].domain
        if not in_domain_scope(domain, domain_filter):
            continue
        proxy = extractor.value(change_id, records)
        if proxy is None:
            continue
        if (
            authoritative is not None
            and authoritative.label_source == LabelSource.HUMAN_AUDIT.value
            and authoritative.label is not None
        ):
            labeled.append(ProxyPair(change_id, domain, proxy, bool(authoritative.label)))
        else:
            unlabeled.append(proxy)
    logger.debug(
        "proxy %s: %d labelled pair(s), %d unlabelled value(s) [domain_filter=%s]",
        extractor.name,
        len(labeled),
        len(unlabeled),
        domain_filter,
    )
    return ProxyDataset(extractor.name, tuple(labeled), tuple(unlabeled))


def _standardise(xs: Sequence[float]) -> list[float]:
    """Min-max the proxy into ``[0, 1]``.

    The PPI estimator targets a probability, so it requires a bounded proxy; an external
    judge's scores (the ``--judge-scores`` seam) carry no such contract. Rescaling is
    lossless for this purpose because the estimator's ``lambda`` is scale-free — only the
    proxy's *shape* matters, and a monotone affine map preserves it exactly.
    """
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return [0.0] * len(xs)
    return [(x - lo) / (hi - lo) for x in xs]


__all__ = [
    "ProxyPair",
    "ProxyDataset",
    "build_dataset",
    "standardise",
]
