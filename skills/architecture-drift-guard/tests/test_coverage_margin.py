"""Targeted tests for previously-uncovered validation/interpolation error branches.

These cover the defensive paths in ``manifest.validate`` / ``load_manifest`` and the
``fold_to_components`` unmapped-source branch, lifting the skill above its coverage gate
with comfortable margin across the Python matrix.
"""

from __future__ import annotations

import pytest
from adguard.errors import ManifestError
from adguard.folding import fold_to_components
from adguard.manifest import Manifest, interpolate, load_manifest, validate
from adguard.migrations import SCHEMA_VERSION


def _manifest(**overrides) -> Manifest:
    base = dict(
        schema_version=SCHEMA_VERSION,
        root_packages=["pkg"],
        components={"api": ["pkg.api"]},
        dependencies=set(),
    )
    base.update(overrides)
    return Manifest(**base)


def test_empty_root_package_entry_rejected() -> None:
    with pytest.raises(ManifestError, match="empty entry"):
        validate(_manifest(root_packages=["pkg", ""]))


def test_empty_component_name_rejected() -> None:
    with pytest.raises(ManifestError, match="component name must be non-empty"):
        validate(_manifest(components={"": ["pkg.api"]}))


def test_empty_package_prefix_rejected() -> None:
    with pytest.raises(ManifestError, match="empty package prefix"):
        validate(_manifest(components={"api": [""]}))


def test_edge_from_unknown_component_rejected() -> None:
    with pytest.raises(ManifestError, match="from unknown component"):
        validate(_manifest(dependencies={("ghost", "api")}))


def test_load_manifest_missing_file_raises(tmp_path) -> None:
    with pytest.raises(ManifestError, match="cannot read manifest"):
        load_manifest(tmp_path / "does-not-exist.yaml")


def test_load_manifest_invalid_yaml_raises(tmp_path) -> None:
    bad = tmp_path / "architecture.yaml"
    bad.write_text("components: [unclosed\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(bad)


def test_interpolate_uncoercible_token_stays_string() -> None:
    # The env value is not valid YAML, so the scalar-coercion fallback returns the raw text.
    assert interpolate("${VAR}", {"VAR": "[unclosed"}) == "[unclosed"


def test_fold_skips_unmapped_source_module() -> None:
    edges = fold_to_components({"orphan.module": {"pkg.api"}}, {"api": ["pkg.api"]})
    assert edges == set()


def test_debug_span_without_fields(caplog) -> None:
    import logging as _logging

    from adguard.logging_util import debug_span

    log = _logging.getLogger("adguard.test.span")
    with caplog.at_level(_logging.DEBUG, logger="adguard.test.span"), debug_span(log, "no-fields-span"):
        pass
    messages = [r.message for r in caplog.records]
    assert any("ENTER no-fields-span" in m for m in messages)
    assert any("EXIT" in m for m in messages)
