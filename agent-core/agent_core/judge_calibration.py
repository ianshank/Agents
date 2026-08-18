"""Judge bias probes: order-flip, verbosity-sensitivity, self-preference.

Pure, dependency-free measurements of systematic judge biases that agreement
(Cohen's kappa) alone cannot detect: a judge can clear a human-agreement floor
while still preferring whichever answer it sees first, whichever is longer, or
whichever its own model family produced. Every probe reuses
:func:`agent_core.calibration.wilson_interval` for its confidence interval —
no new interval math — and follows :func:`agent_core.calibration.evaluate_calibration`'s
shape: a pure function that takes explicit targets (:class:`~agent_core.config.ProbeConfig`)
and returns a report carrying its own ``passes`` verdict.

Every probe takes plain parallel sequences or a small local record type (never
:class:`~agent_core.golden.GoldenItem` or a pairwise corpus type), so this
module has no dependency on *how* a pair was judged or where it came from —
mirroring how :mod:`agent_core.calibration` has no notion of what produced its
probabilities.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .calibration import wilson_interval
from .config import ProbeConfig

#: A judge's verdict for one judged pair: which side won, or a tie.
Verdict = str  # "a" | "b" | "tie" — not a Literal so callers aren't forced to import one

_VALID_VERDICTS = ("a", "b", "tie")
_SWAP = {"a": "b", "b": "a", "tie": "tie"}


def _check_verdicts(verdicts: Sequence[str], *, name: str) -> None:
    if not verdicts:
        raise ValueError(f"{name}: empty input")
    bad = sorted({v for v in verdicts if v not in _VALID_VERDICTS})
    if bad:
        raise ValueError(f"{name}: verdicts must be 'a', 'b' or 'tie', got {bad!r}")


# --- order-flip ---------------------------------------------------------------
@dataclass(frozen=True)
class OrderProbeResult:
    n: int
    flips: int
    flip_rate: float
    ci_low: float
    ci_high: float
    passes: bool


def order_flip_rate(
    verdicts_ab: Sequence[str], verdicts_ba: Sequence[str], cfg: ProbeConfig
) -> OrderProbeResult:
    """Rate at which swapping presentation order changes the winner.

    ``verdicts_ab[i]`` is the verdict when pair *i* was shown as (A, B);
    ``verdicts_ba[i]`` is the verdict for the *same* pair shown as (B, A). A
    flip is recorded when the original-terms winner differs between the two
    orderings — ``verdicts_ba`` is translated back to original terms via
    :data:`_SWAP` before comparing, since "a" in the swapped ordering means
    the first-shown candidate (B) won.
    """
    _check_verdicts(verdicts_ab, name="verdicts_ab")
    _check_verdicts(verdicts_ba, name="verdicts_ba")
    if len(verdicts_ab) != len(verdicts_ba):
        raise ValueError("order_flip_rate: verdicts_ab and verdicts_ba must have equal length")
    n = len(verdicts_ab)
    flips = sum(1 for ab, ba in zip(verdicts_ab, verdicts_ba, strict=True) if ab != _SWAP[ba])
    flip_rate = flips / n
    ci_low, ci_high = wilson_interval(flips, n, cfg.wilson_z)
    return OrderProbeResult(
        n=n,
        flips=flips,
        flip_rate=flip_rate,
        ci_low=ci_low,
        ci_high=ci_high,
        passes=flip_rate <= cfg.order_flip_tolerance,
    )


# --- verbosity sensitivity ------------------------------------------------------
@dataclass(frozen=True)
class VerbosityProbeResult:
    n: int  # non-tied pairs only — a tie carries no length-preference signal
    ties: int
    concise_wins: int
    expanded_wins: int
    expanded_win_rate: float
    preference_delta: float  # expanded_win_rate - 0.5; positive = biased toward longer
    ci_low: float
    ci_high: float
    passes: bool


def verbosity_preference_delta(verdicts: Sequence[str], cfg: ProbeConfig) -> VerbosityProbeResult:
    """Preference for the longer of two semantically-equivalent answers.

    ``verdicts``: one entry per judged (concise, expanded) pair, each
    ``"concise"`` | ``"expanded"`` | ``"tie"``. The confidence interval is on
    ``expanded_win_rate`` among non-tied pairs (a proportion in [0, 1]);
    ``preference_delta`` is that rate's deviation from the unbiased 50/50
    expectation, so a positive value names a bias toward longer answers and a
    negative value names a bias toward shorter ones.
    """
    if not verdicts:
        raise ValueError("verbosity_preference_delta: empty input")
    bad = sorted({v for v in verdicts if v not in ("concise", "expanded", "tie")})
    if bad:
        raise ValueError(
            f"verbosity_preference_delta: verdicts must be 'concise', 'expanded' or 'tie'"
            f", got {bad!r}"
        )

    ties = sum(1 for v in verdicts if v == "tie")
    concise_wins = sum(1 for v in verdicts if v == "concise")
    expanded_wins = sum(1 for v in verdicts if v == "expanded")
    n = concise_wins + expanded_wins
    if n == 0:
        raise ValueError(
            "verbosity_preference_delta: no non-tied pairs to measure a preference from"
        )

    expanded_win_rate = expanded_wins / n
    preference_delta = expanded_win_rate - 0.5
    ci_low, ci_high = wilson_interval(expanded_wins, n, cfg.wilson_z)
    return VerbosityProbeResult(
        n=n,
        ties=ties,
        concise_wins=concise_wins,
        expanded_wins=expanded_wins,
        expanded_win_rate=expanded_win_rate,
        preference_delta=preference_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        passes=abs(preference_delta) <= cfg.verbosity_delta_tolerance,
    )


# --- self-preference -----------------------------------------------------------
@dataclass(frozen=True)
class PairOutcome:
    """One judged pair's outcome, family-labelled.

    Deliberately independent of any pairwise corpus type (Group 2) — probe
    math has no dependency on where a pair came from.
    """

    family_a: str
    family_b: str
    winner: str  # "a" | "b" | "tie"


@dataclass(frozen=True)
class SelfPreferenceResult:
    judge_family: str
    same_family_n: int
    same_family_win_rate: float
    same_family_ci_low: float
    same_family_ci_high: float
    other_family_n: int
    other_family_win_rate: float
    other_family_ci_low: float
    other_family_ci_high: float
    delta: float  # same_family_win_rate - other_family_win_rate
    passes: bool


def self_preference_breakdown(
    judge_family: str, outcomes: Sequence[PairOutcome], cfg: ProbeConfig
) -> SelfPreferenceResult:
    """Win-rate breakdown by whether the winning candidate shares the judge's family.

    Only pairs where *exactly one* candidate is ``judge_family`` are
    informative — a pair where both or neither candidate share it cannot show
    self-preference, and a tie carries no winner signal either way. Every
    informative, non-tied pair has exactly one winner, so
    ``other_family_win_rate`` is always ``1 - same_family_win_rate``; both are
    reported for readability, matching :func:`verbosity_preference_delta`
    reporting both `concise_wins` and `expanded_wins`.
    """
    if not outcomes:
        raise ValueError("self_preference_breakdown: empty input")

    same_wins = same_total = 0
    for o in outcomes:
        if o.winner not in _VALID_VERDICTS:
            raise ValueError(
                f"self_preference_breakdown: winner must be 'a', 'b' or 'tie', got {o.winner!r}"
            )
        a_is_judge = o.family_a == judge_family
        b_is_judge = o.family_b == judge_family
        if a_is_judge == b_is_judge or o.winner == "tie":
            continue  # both/neither family, or a tie: uninformative for self-preference
        same_total += 1
        if (o.winner == "a") == a_is_judge:
            same_wins += 1

    if same_total == 0:
        raise ValueError(
            "self_preference_breakdown: no non-tied pairs with exactly one judge-family candidate"
        )

    other_total = same_total
    other_wins = same_total - same_wins
    same_rate = same_wins / same_total
    other_rate = other_wins / other_total
    same_ci_low, same_ci_high = wilson_interval(same_wins, same_total, cfg.wilson_z)
    other_ci_low, other_ci_high = wilson_interval(other_wins, other_total, cfg.wilson_z)
    delta = same_rate - other_rate
    return SelfPreferenceResult(
        judge_family=judge_family,
        same_family_n=same_total,
        same_family_win_rate=same_rate,
        same_family_ci_low=same_ci_low,
        same_family_ci_high=same_ci_high,
        other_family_n=other_total,
        other_family_win_rate=other_rate,
        other_family_ci_low=other_ci_low,
        other_family_ci_high=other_ci_high,
        delta=delta,
        passes=delta <= cfg.self_preference_tolerance,
    )
