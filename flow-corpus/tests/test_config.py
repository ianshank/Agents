"""CorpusConfig validation + derived indeterminate cap."""

from __future__ import annotations

import pytest

from flow_corpus.config import CorpusConfig


def test_derived_indeterminate_rate() -> None:
    cfg = CorpusConfig(audit_capacity_per_cycle=30, corpus_volume_per_cycle=200)
    assert cfg.max_indeterminate_rate == pytest.approx(0.15)


def test_derived_rate_is_not_stored_literal() -> None:
    # Changing the budget changes the cap (it is derived, not hardcoded).
    a = CorpusConfig(audit_capacity_per_cycle=10, corpus_volume_per_cycle=100)
    b = CorpusConfig(audit_capacity_per_cycle=50, corpus_volume_per_cycle=100)
    assert a.max_indeterminate_rate == pytest.approx(0.1)
    assert b.max_indeterminate_rate == pytest.approx(0.5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"corpus_volume_per_cycle": 0},
        {"audit_capacity_per_cycle": -1},
        {"min_oracle_kappa": 1.5},
        {"n_bins": 0},
    ],
)
def test_invalid_config_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        CorpusConfig(**kwargs)
