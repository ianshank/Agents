"""Tests for deterministic Mermaid C4 rendering and freshness normalisation."""
from __future__ import annotations

from adguard.manifest import Manifest
from adguard.mermaid import _alias, normalize_text, render_mermaid


def _manifest(**kw) -> Manifest:
    base = dict(
        schema_version="1.0.0",
        root_packages=["pkg"],
        components={"api": ["pkg.api"], "core": ["pkg.core"]},
        dependencies={("api", "core")},
    )
    base.update(kw)
    return Manifest(**base)


GOLDEN = (
    "C4Component\n"
    "    title Architecture — Component View\n"
    "\n"
    '    Component(api, "api", "Component")\n'
    '    Component(core, "core", "Component")\n'
    "\n"
    '    Rel(api, core, "")\n'
)


def test_render_matches_golden():
    assert render_mermaid(_manifest()) == GOLDEN


def test_render_is_idempotent():
    m = _manifest()
    assert render_mermaid(m) == render_mermaid(m)


def test_render_custom_title():
    out = render_mermaid(_manifest(output={"title": "My Title"}))
    assert "    title My Title\n" in out


def test_render_without_edges_omits_rel_block():
    out = render_mermaid(_manifest(dependencies=set()))
    assert "Rel(" not in out
    assert out.endswith('Component(core, "core", "Component")\n')


def test_normalize_text_strips_trailing_and_single_newline():
    assert normalize_text("a  \r\nb\n\n\n") == "a\nb\n"


def test_alias_sanitizes_non_word_chars():
    assert _alias("pay-service") == "pay_service"


def test_alias_prefixes_leading_digit():
    assert _alias("3d") == "c_3d"


def test_alias_empty_falls_back():
    assert _alias("") == "c"
