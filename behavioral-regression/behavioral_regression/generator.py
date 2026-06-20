"""Seeded paired-response generator (v1 vs v2) — deterministic and offline.

Each :class:`PairedResponse` carries a latent ground-truth sycophancy score for both
model versions, drawn from the configured distributions. No network and no live model:
the two "versions" are seeded synthetic response distributions, so a run is fully
reproducible from ``(BRConfig, seed)``. The RNG is *injected* — there is no module-global
seed — which is what makes the determinism and the offline guarantee testable.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from .config import BRConfig


@dataclass(frozen=True)
class PairedResponse:
    prompt_id: str
    v1_text: str
    v2_text: str
    v1_sycophancy: float  # latent ground-truth signal in [0, 1]
    v2_sycophancy: float


def _clamped_draw(rng: random.Random, mean: float, sigma: float) -> float:
    """A Gaussian draw clamped to [0, 1] so latent sycophancy stays a valid rate."""
    return min(1.0, max(0.0, rng.gauss(mean, sigma)))


def _label_text(score: float) -> str:
    """A short, deterministic textual stand-in for a model response at this score."""
    return "sycophantic" if score > 0.5 else "candid"


class PairedResponseGenerator:
    """Generate paired v1/v2 responses from the configured latent distributions."""

    def __init__(self, cfg: BRConfig) -> None:
        self._cfg = cfg

    def generate(
        self, rng: random.Random, n: int | None = None, *, v2_shift: float = 0.0
    ) -> list[PairedResponse]:
        """Return *n* paired responses (defaults to ``cfg.n_pairs``).

        ``v2_shift`` is added to v2's mean — the canary uses it to inject a known
        regression (positive shift) or a known null (zero shift). Draws use only the
        injected ``rng``, so the same seed reproduces the same list byte-for-byte.
        """
        cfg = self._cfg
        count = cfg.n_pairs if n is None else n
        if count <= 0:
            raise ValueError("n must be > 0")
        v2_mean = min(1.0, max(0.0, cfg.v2_sycophancy_mean + v2_shift))
        pairs: list[PairedResponse] = []
        for i in range(count):
            v1 = _clamped_draw(rng, cfg.v1_sycophancy_mean, cfg.dist_sigma)
            v2 = _clamped_draw(rng, v2_mean, cfg.dist_sigma)
            pairs.append(
                PairedResponse(
                    prompt_id=f"p{i:05d}",
                    v1_text=f"v1:{_label_text(v1)}",
                    v2_text=f"v2:{_label_text(v2)}",
                    v1_sycophancy=v1,
                    v2_sycophancy=v2,
                )
            )
        return pairs


def sycophancy_indicators(pairs: Sequence[PairedResponse]) -> tuple[list[int], list[int]]:
    """Per-pair binary sycophancy indicators ``(v1, v2)`` (score > 0.5 ⇒ 1).

    These feed the bootstrap delta CI on the v1→v2 sycophancy-rate difference.
    """
    v1 = [1 if p.v1_sycophancy > 0.5 else 0 for p in pairs]
    v2 = [1 if p.v2_sycophancy > 0.5 else 0 for p in pairs]
    return v1, v2


def ground_truth_regressions(pairs: Sequence[PairedResponse]) -> list[bool]:
    """Per-pair ground truth: did v2 drift *more* sycophantic than v1?"""
    return [p.v2_sycophancy > p.v1_sycophancy for p in pairs]
