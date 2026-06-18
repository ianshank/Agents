"""Guards that pytest/Hypothesis config stays strict and self-describing."""

from __future__ import annotations

from hypothesis import settings


def test_hypothesis_profiles_registered() -> None:
    # get_profile raises if a profile is missing; calling it is the assertion.
    for name in ("dev", "ci"):
        assert settings.get_profile(name) is not None


def test_markers_registered(pytestconfig) -> None:
    names = {m.split(":")[0].strip() for m in pytestconfig.getini("markers")}
    assert {"slow", "property"} <= names
