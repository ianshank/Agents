import pytest

from agent_core import ProbeConfig
from agent_core.judge_calibration import (
    PairOutcome,
    order_flip_rate,
    self_preference_breakdown,
    verbosity_preference_delta,
)

CFG = ProbeConfig()


# --- order_flip_rate ---------------------------------------------------------


def test_order_flip_rate_no_flips_when_position_independent():
    # A wins as (A,B); when swapped to (B,A), the second position (A) wins -> consistent.
    result = order_flip_rate(["a", "b"], ["b", "a"], CFG)
    assert result.n == 2
    assert result.flips == 0
    assert result.flip_rate == 0.0
    assert result.passes is True


def test_order_flip_rate_all_flips_when_first_position_always_wins():
    # First-shown candidate always wins, regardless of which original answer it is.
    result = order_flip_rate(["a", "a"], ["a", "a"], CFG)
    # pair 0: ab='a' (A won); ba='a' means first-shown (B) won -> swap('a')='b'; 'a' != 'b' -> flip
    # pair 1: same pattern -> flip
    assert result.flips == 2
    assert result.flip_rate == 1.0
    assert result.passes is False


def test_order_flip_rate_ties_do_not_flip_against_ties():
    result = order_flip_rate(["tie"], ["tie"], CFG)
    assert result.flips == 0


def test_order_flip_rate_respects_tolerance():
    lenient = ProbeConfig(order_flip_tolerance=1.0)
    result = order_flip_rate(["a", "a"], ["a", "a"], lenient)
    assert result.flip_rate == 1.0
    assert result.passes is True


def test_order_flip_rate_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="equal length"):
        order_flip_rate(["a"], ["a", "b"], CFG)


def test_order_flip_rate_rejects_invalid_verdicts():
    with pytest.raises(ValueError, match="verdicts_ab"):
        order_flip_rate(["x"], ["a"], CFG)


def test_order_flip_rate_rejects_empty_input():
    with pytest.raises(ValueError, match="empty input"):
        order_flip_rate([], [], CFG)


# --- verbosity_preference_delta ----------------------------------------------


def test_verbosity_no_bias_when_evenly_split():
    result = verbosity_preference_delta(["concise", "expanded"], CFG)
    assert result.preference_delta == 0.0
    assert result.passes is True


def test_verbosity_bias_toward_longer():
    result = verbosity_preference_delta(["expanded", "expanded", "expanded", "concise"], CFG)
    assert result.expanded_wins == 3
    assert result.concise_wins == 1
    assert result.expanded_win_rate == 0.75
    assert result.preference_delta == pytest.approx(0.25)
    assert result.passes is False  # exceeds the default 0.15 tolerance


def test_verbosity_bias_toward_shorter_is_also_flagged():
    """The check is symmetric — a judge that penalises length is also biased."""
    result = verbosity_preference_delta(["concise", "concise", "concise", "expanded"], CFG)
    assert result.preference_delta == pytest.approx(-0.25)
    assert result.passes is False


def test_verbosity_ties_excluded_from_rate_but_counted():
    result = verbosity_preference_delta(["tie", "tie", "concise", "expanded"], CFG)
    assert result.ties == 2
    assert result.n == 2  # only the non-tied pairs
    assert result.expanded_win_rate == 0.5


def test_verbosity_rejects_all_ties():
    with pytest.raises(ValueError, match="no non-tied pairs"):
        verbosity_preference_delta(["tie", "tie"], CFG)


def test_verbosity_rejects_invalid_verdicts():
    with pytest.raises(ValueError, match="verdicts must be"):
        verbosity_preference_delta(["a"], CFG)


def test_verbosity_rejects_empty_input():
    with pytest.raises(ValueError, match="empty input"):
        verbosity_preference_delta([], CFG)


# --- self_preference_breakdown -----------------------------------------------


def test_self_preference_none_when_balanced():
    outcomes = [
        PairOutcome("gpt", "claude", "a"),  # gpt (judge family) wins
        PairOutcome("claude", "gpt", "a"),  # claude wins -> gpt (judge family) loses
    ]
    result = self_preference_breakdown("gpt", outcomes, CFG)
    assert result.same_family_n == 2
    assert result.same_family_win_rate == 0.5
    assert result.delta == 0.0
    assert result.passes is True


def test_self_preference_favours_own_family():
    outcomes = [
        PairOutcome("gpt", "claude", "a"),
        PairOutcome("gpt", "claude", "a"),
        PairOutcome("claude", "gpt", "b"),  # gpt wins again (family_b)
        PairOutcome("claude", "gpt", "a"),  # claude wins -> gpt loses
    ]
    result = self_preference_breakdown("gpt", outcomes, CFG)
    assert result.same_family_n == 4
    assert result.same_family_win_rate == 0.75
    assert result.other_family_win_rate == 0.25
    assert result.delta == pytest.approx(0.5)
    assert result.passes is False


def test_self_preference_excludes_uninformative_pairs():
    outcomes = [
        PairOutcome("gpt", "gpt", "a"),  # both judge family -- uninformative
        PairOutcome("claude", "mistral", "a"),  # neither judge family -- uninformative
        PairOutcome("gpt", "claude", "tie"),  # tie -- uninformative
        PairOutcome("gpt", "claude", "a"),  # the only informative pair
    ]
    result = self_preference_breakdown("gpt", outcomes, CFG)
    assert result.same_family_n == 1
    assert result.same_family_win_rate == 1.0


def test_self_preference_rejects_no_informative_pairs():
    outcomes = [PairOutcome("gpt", "gpt", "a")]
    with pytest.raises(ValueError, match="no non-tied pairs"):
        self_preference_breakdown("gpt", outcomes, CFG)


def test_self_preference_rejects_invalid_winner():
    outcomes = [PairOutcome("gpt", "claude", "x")]
    with pytest.raises(ValueError, match="winner must be"):
        self_preference_breakdown("gpt", outcomes, CFG)


def test_self_preference_rejects_empty_input():
    with pytest.raises(ValueError, match="empty input"):
        self_preference_breakdown("gpt", [], CFG)
