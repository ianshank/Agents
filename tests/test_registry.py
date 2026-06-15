from __future__ import annotations

import pytest

from eval_harness.core.registry import Registry, RegistryError


def test_register_and_create():
    reg: Registry = Registry("widget")

    @reg.register("foo", aliases=("bar",))
    class Foo:
        def __init__(self, x=1):
            self.x = x

    assert "foo" in reg
    assert "bar" in reg
    assert reg.names() == ["foo"]
    obj = reg.create("foo", {"x": 5})
    assert obj.x == 5
    # alias resolves to the same class
    assert reg.create("bar").x == 1


def test_unknown_raises():
    reg: Registry = Registry("widget")
    with pytest.raises(RegistryError):
        reg.get("missing")


def test_duplicate_registration_rejected():
    reg: Registry = Registry("widget")

    @reg.register("dup")
    class A:
        pass

    with pytest.raises(RegistryError):
        @reg.register("dup")
        class B:
            pass
