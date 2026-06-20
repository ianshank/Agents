"""Version-key tests: deterministic, order-independent, task-excluded."""

from __future__ import annotations

from flow_corpus.keying import version_key


def test_key_is_deterministic() -> None:
    a = version_key("mcts@1", {"skill": 0.7, "n_rollouts": 5})
    b = version_key("mcts@1", {"skill": 0.7, "n_rollouts": 5})
    assert a == b


def test_key_is_order_independent() -> None:
    a = version_key("mcts@1", {"skill": 0.7, "n_rollouts": 5})
    b = version_key("mcts@1", {"n_rollouts": 5, "skill": 0.7})
    assert a == b


def test_impl_change_rekeys() -> None:
    assert version_key("mcts@1", {"skill": 0.7}) != version_key("mcts@2", {"skill": 0.7})


def test_config_change_rekeys() -> None:
    assert version_key("mcts@1", {"skill": 0.7}) != version_key("mcts@1", {"skill": 0.8})


def test_nested_config_canonicalised() -> None:
    a = version_key("x@1", {"opts": {"b": 1, "a": 2}, "list": [1, 2]})
    b = version_key("x@1", {"list": [1, 2], "opts": {"a": 2, "b": 1}})
    assert a == b
