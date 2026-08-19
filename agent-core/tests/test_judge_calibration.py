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
    assert result.degenerate is None  # default min_pairs=1 never trips the floor


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


def test_order_flip_rate_undersized_fails_despite_clearing_tolerance():
    """A 1-pair sample clears the default tolerance (0 flips) but not a strict min_pairs floor."""
    strict = ProbeConfig(min_pairs=30)
    result = order_flip_rate(["a"], ["b"], strict)
    assert result.flip_rate == 0.0  # would tolerance-pass on its own
    assert result.passes is False  # min_pairs=30 > n=1
    assert result.degenerate == "insufficient pairs: n=1 < min_pairs=30"


def test_order_flip_rate_boundary_n_equals_min_pairs_clears_the_floor():
    """The floor is at-least semantics (n < cfg.min_pairs, not <=) -- n exactly
    equal to min_pairs must clear it, not trip it."""
    exact = ProbeConfig(min_pairs=2)
    result = order_flip_rate(["a", "b"], ["b", "a"], exact)  # n=2
    assert result.n == 2
    assert result.degenerate is None


def test_order_flip_rate_undersized_and_tolerance_failing_both_hold():
    """A sample can fail its own tolerance *and* be undersized at once -- passes
    must stay False and degenerate must still be set, not just one or the other."""
    strict = ProbeConfig(min_pairs=30)
    result = order_flip_rate(["a", "a"], ["a", "a"], strict)  # n=2, flip_rate=1.0
    assert result.flip_rate > strict.order_flip_tolerance  # genuinely tolerance-fails too
    assert result.degenerate == "insufficient pairs: n=2 < min_pairs=30"
    assert result.passes is False


def test_order_flip_rate_mixed_tie_and_decisive_pairs():
    """A corpus mixing tied and decisive pairs was previously untested -- only
    all-tie or all-decisive corpora existed."""
    result = order_flip_rate(["tie", "a"], ["a", "tie"], CFG)
    assert result.n == 2
    assert result.flips == 2  # tie->a and a->tie both count as a changed winner
    assert result.flip_rate == 1.0


def test_order_flip_rate_logs_degeneracy_for_operator_visibility(caplog):
    strict = ProbeConfig(min_pairs=30)
    with caplog.at_level("WARNING", logger="agent_core.judge_calibration"):
        order_flip_rate(["a"], ["b"], strict)
    assert any("insufficient pairs" in r.message for r in caplog.records)


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
    assert result.degenerate is None  # default min_pairs=1 never trips the floor


def test_verbosity_undersized_fails_despite_zero_delta():
    strict = ProbeConfig(min_pairs=30)
    result = verbosity_preference_delta(["concise", "expanded"], strict)  # n=2, delta=0.0
    assert result.preference_delta == 0.0
    assert result.passes is False
    assert result.degenerate == "insufficient pairs: n=2 < min_pairs=30"


def test_verbosity_boundary_n_equals_min_pairs_clears_the_floor():
    exact = ProbeConfig(min_pairs=2)
    result = verbosity_preference_delta(["concise", "expanded"], exact)  # n=2
    assert result.n == 2
    assert result.degenerate is None


def test_verbosity_min_pairs_counts_informative_pairs_not_raw_length():
    """Padding with ties inflates raw input length without inflating n -- min_pairs
    must compare against the informative (non-tied) count, not len(verdicts)."""
    cfg = ProbeConfig(min_pairs=5)
    verdicts = ["tie"] * 10 + ["concise", "expanded"]  # n=2, raw length=12
    result = verbosity_preference_delta(verdicts, cfg)
    assert result.n == 2
    assert result.degenerate == "insufficient pairs: n=2 < min_pairs=5"


def test_verbosity_single_pair_corpus():
    """n=1 was the smallest untested corpus size (existing tests start at n=2)."""
    result = verbosity_preference_delta(["expanded"], CFG)
    assert result.n == 1
    assert result.expanded_win_rate == 1.0
    assert result.preference_delta == 0.5


def test_verbosity_logs_degeneracy_for_operator_visibility(caplog):
    strict = ProbeConfig(min_pairs=30)
    with caplog.at_level("WARNING", logger="agent_core.judge_calibration"):
        verbosity_preference_delta(["concise", "expanded"], strict)
    assert any("insufficient pairs" in r.message for r in caplog.records)


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
    assert result.degenerate is None  # default min_pairs=1 never trips the floor


def test_self_preference_undersized_fails_despite_balanced_delta():
    strict = ProbeConfig(min_pairs=30)
    outcomes = [
        PairOutcome("gpt", "claude", "a"),
        PairOutcome("claude", "gpt", "a"),
    ]  # same_family_n=2, delta=0.0
    result = self_preference_breakdown("gpt", outcomes, strict)
    assert result.delta == 0.0
    assert result.passes is False
    assert result.degenerate == "insufficient pairs: n=2 < min_pairs=30"


def test_self_preference_boundary_n_equals_min_pairs_clears_the_floor():
    exact = ProbeConfig(min_pairs=2)
    outcomes = [
        PairOutcome("gpt", "claude", "a"),
        PairOutcome("claude", "gpt", "a"),
    ]  # same_family_n=2
    result = self_preference_breakdown("gpt", outcomes, exact)
    assert result.same_family_n == 2
    assert result.degenerate is None


def test_self_preference_min_pairs_counts_informative_pairs_not_raw_length():
    """Padding with uninformative pairs (both/neither judge-family) inflates raw
    input length without inflating same_family_n -- min_pairs must compare
    against the informative count, not len(outcomes)."""
    cfg = ProbeConfig(min_pairs=5)
    outcomes = (
        [PairOutcome("gpt", "gpt", "a")] * 5  # both judge family -- uninformative
        + [PairOutcome("claude", "mistral", "a")] * 5  # neither judge family -- uninformative
        + [PairOutcome("gpt", "claude", "a"), PairOutcome("claude", "gpt", "a")]  # informative
    )  # same_family_n=2, raw length=12
    result = self_preference_breakdown("gpt", outcomes, cfg)
    assert result.same_family_n == 2
    assert result.degenerate == "insufficient pairs: n=2 < min_pairs=5"


def test_self_preference_logs_degeneracy_for_operator_visibility(caplog):
    strict = ProbeConfig(min_pairs=30)
    outcomes = [PairOutcome("gpt", "claude", "a"), PairOutcome("claude", "gpt", "a")]
    with caplog.at_level("WARNING", logger="agent_core.judge_calibration"):
        self_preference_breakdown("gpt", outcomes, strict)
    assert any("insufficient pairs" in r.message for r in caplog.records)


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
