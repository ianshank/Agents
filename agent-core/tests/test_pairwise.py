import pytest

from agent_core.pairwise import PairwiseItem, PairwiseSet


def _item(item_id="i1", **overrides) -> PairwiseItem:
    defaults = dict(
        item_id=item_id,
        prompt="which is better?",
        answer_a="short answer",
        answer_b="longer, more detailed answer",
        family_a="gpt",
        family_b="claude",
    )
    defaults.update(overrides)
    return PairwiseItem(**defaults)


def test_invalid_expected_raises():
    with pytest.raises(ValueError, match="expected"):
        _item(expected="x")


def test_expected_none_is_valid():
    item = _item(expected=None)
    assert item.expected is None


def test_item_equality():
    a = _item()
    b = _item()
    assert a == b
    assert hash(a) == hash(b)
    assert _item(item_id="i2") != a


def test_item_equality_against_wrong_type():
    assert _item() != "not a PairwiseItem"


def test_pairwise_set_hash_and_equality_against_wrong_type():
    pw = PairwiseSet((_item(),))
    assert hash(pw) == hash(frozenset(pw.items))
    assert pw != "not a PairwiseSet"


def test_pairwise_set_rejects_duplicate_ids():
    with pytest.raises(Exception, match="duplicate"):
        PairwiseSet((_item("dup"), _item("dup")))


def test_pairwise_set_equality_is_order_independent():
    a = PairwiseSet((_item("i1"), _item("i2")))
    b = PairwiseSet((_item("i2"), _item("i1")))
    assert a == b


def test_jsonl_round_trip_is_exact():
    items = (_item("i1"), _item("i2", expected="a"))
    original = PairwiseSet(items)
    restored = PairwiseSet.from_jsonl(original.to_jsonl())
    assert restored == original


def test_jsonl_is_deterministic_byte_for_byte():
    items = (_item("z"), _item("a"))
    text1 = PairwiseSet(items).to_jsonl()
    text2 = PairwiseSet(tuple(reversed(items))).to_jsonl()
    assert text1 == text2  # sorted by item_id regardless of insertion order


def test_from_jsonl_skips_empty_lines():
    text = "\n" + PairwiseSet((_item(),)).to_jsonl() + "\n"
    restored = PairwiseSet.from_jsonl(text)
    assert len(restored.items) == 1


# --- canaries -----------------------------------------------------------------


def test_known_equal_canary_requires_tie_expected():
    with pytest.raises(ValueError, match="known_equal"):
        _item(canary_kind="known_equal", expected="a")


def test_known_equal_canary_with_tie_is_valid():
    item = _item(canary_kind="known_equal", expected="tie")
    assert item.canary_kind == "known_equal"


@pytest.mark.parametrize("kind", ["clearly_better", "clearly_worse"])
def test_directional_canary_requires_a_or_b_expected(kind):
    with pytest.raises(ValueError, match=kind):
        _item(canary_kind=kind, expected="tie")


@pytest.mark.parametrize("kind", ["clearly_better", "clearly_worse"])
def test_directional_canary_with_a_or_b_is_valid(kind):
    item = _item(canary_kind=kind, expected="a")
    assert item.canary_kind == kind


def test_invalid_canary_kind_raises():
    with pytest.raises(ValueError, match="canary_kind"):
        _item(canary_kind="bogus", expected="a")


def test_canaries_property_filters_correctly():
    plain = _item("plain")
    canary = _item("canary", canary_kind="known_equal", expected="tie")
    pw = PairwiseSet((plain, canary))
    assert pw.canaries == (canary,)


def test_canaries_round_trip_through_jsonl():
    canary = _item("canary", canary_kind="clearly_better", expected="a")
    restored = PairwiseSet.from_jsonl(PairwiseSet((canary,)).to_jsonl())
    assert restored.canaries == (canary,)
