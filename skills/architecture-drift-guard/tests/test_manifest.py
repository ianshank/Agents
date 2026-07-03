"""Tests for manifest loading, interpolation, overrides, and validation."""

from __future__ import annotations

import textwrap

import pytest
from adguard.errors import ManifestError
from adguard.manifest import (
    DEFAULT_MERMAID_PATH,
    Manifest,
    apply_overrides,
    interpolate,
    load_manifest,
    validate,
)


def _write(tmp_path, body: str):
    path = tmp_path / "architecture.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


VALID = """
    schema_version: "1.0.0"
    root_packages: [pkg]
    components:
      api: [pkg.api]
      core: [pkg.core]
    dependencies:
      api: [core]
"""


def test_load_valid_manifest(tmp_path):
    m = load_manifest(_write(tmp_path, VALID))
    assert m.root_packages == ["pkg"]
    assert m.components == {"api": ["pkg.api"], "core": ["pkg.core"]}
    assert m.dependencies == {("api", "core")}
    assert m.mermaid_path() == DEFAULT_MERMAID_PATH


def test_interpolate_env_with_default():
    out = interpolate({"p": "${MISSING:-fallback}/src"}, env={})
    assert out == {"p": "fallback/src"}


def test_interpolate_env_present():
    out = interpolate("${HOME_DIR}", env={"HOME_DIR": "/x"})
    assert out == "/x"


def test_interpolate_exact_token_coerces_scalar():
    assert interpolate("${N}", env={"N": "true"}) is True


def test_interpolate_missing_without_default_raises():
    with pytest.raises(ManifestError, match="not set and has no default"):
        interpolate("${NOPE}", env={})


def test_sys_path_interpolation_in_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_ROOT", "/repo")
    body = VALID + '    sys_path: ["${REPO_ROOT}/src"]\n'
    m = load_manifest(_write(tmp_path, body))
    assert m.sys_path == ["/repo/src"]


def test_apply_overrides_dotted_path():
    raw = {"output": {}}
    apply_overrides(raw, ["output.mermaid_path=docs/a.mmd"])
    assert raw["output"]["mermaid_path"] == "docs/a.mmd"


def test_apply_overrides_requires_equals():
    with pytest.raises(ManifestError, match=r"key\.path=value"):
        apply_overrides({}, ["bad"])


def test_apply_overrides_rejects_non_mapping():
    with pytest.raises(ManifestError, match="is not a mapping"):
        apply_overrides({"a": 1}, ["a.b=2"])


def test_override_applied_through_load(tmp_path):
    m = load_manifest(_write(tmp_path, VALID), overrides=["output.mermaid_path=docs/x.mmd"])
    assert m.mermaid_path() == "docs/x.mmd"


def test_missing_schema_version_raises(tmp_path):
    with pytest.raises(ManifestError, match="schema_version"):
        load_manifest(_write(tmp_path, VALID.replace('schema_version: "1.0.0"', "")))


def test_non_mapping_manifest_raises(tmp_path):
    path = tmp_path / "architecture.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="did not parse to a mapping"):
        load_manifest(path)


def test_unknown_component_in_edge_raises(tmp_path):
    body = VALID.replace("api: [core]", "api: [ghost]")
    with pytest.raises(ManifestError, match="unknown component"):
        load_manifest(_write(tmp_path, body))


def test_self_edge_raises(tmp_path):
    body = VALID.replace("api: [core]", "api: [api]")
    with pytest.raises(ManifestError, match="self-edge"):
        load_manifest(_write(tmp_path, body))


def test_empty_root_packages_raises(tmp_path):
    body = VALID.replace("root_packages: [pkg]", "root_packages: []")
    with pytest.raises(ManifestError, match="at least one importable package"):
        load_manifest(_write(tmp_path, body))


def test_component_without_prefixes_raises(tmp_path):
    body = VALID.replace("core: [pkg.core]", "core: []")
    with pytest.raises(ManifestError, match="no package prefixes"):
        load_manifest(_write(tmp_path, body))


def test_components_must_be_mapping(tmp_path):
    body = """
        schema_version: "1.0.0"
        root_packages: [pkg]
        components: [a, b]
    """
    with pytest.raises(ManifestError, match="'components' must be a mapping"):
        load_manifest(_write(tmp_path, body))


def test_component_prefixes_must_be_list(tmp_path):
    body = VALID.replace("api: [pkg.api]", "api: pkg.api")
    with pytest.raises(ManifestError, match="must be a list of package prefixes"):
        load_manifest(_write(tmp_path, body))


def test_dependencies_must_be_mapping(tmp_path):
    body = VALID.replace("dependencies:\n      api: [core]", "dependencies: [a, b]")
    with pytest.raises(ManifestError, match="'dependencies' must be a mapping"):
        load_manifest(_write(tmp_path, body))


def test_dependency_targets_must_be_list(tmp_path):
    body = VALID.replace("api: [core]", "api: core")
    with pytest.raises(ManifestError, match="must be a list of component names"):
        load_manifest(_write(tmp_path, body))


def test_empty_dependencies_allowed(tmp_path):
    body = VALID.replace("dependencies:\n      api: [core]", "dependencies:")
    m = load_manifest(_write(tmp_path, body))
    assert m.dependencies == set()


def test_null_targets_skipped(tmp_path):
    body = VALID.replace("api: [core]", "api:")
    m = load_manifest(_write(tmp_path, body))
    assert m.dependencies == set()


def test_validate_rejects_wrong_schema_version():
    m = Manifest(
        schema_version="0.9",
        root_packages=["pkg"],
        components={"api": ["pkg.api"]},
        dependencies=set(),
    )
    with pytest.raises(ManifestError, match="!= current"):
        validate(m)


def test_root_packages_must_be_list(tmp_path):
    body = VALID.replace("root_packages: [pkg]", "root_packages: pkg")
    with pytest.raises(ManifestError, match="'root_packages' must be a list"):
        load_manifest(_write(tmp_path, body))


def test_sys_path_must_be_list(tmp_path):
    body = VALID + "    sys_path: notalist\n"
    with pytest.raises(ManifestError, match="'sys_path' must be a list"):
        load_manifest(_write(tmp_path, body))


def test_output_must_be_mapping(tmp_path):
    body = VALID + "    output: notamap\n"
    with pytest.raises(ManifestError, match="'output' must be a mapping"):
        load_manifest(_write(tmp_path, body))


def test_no_components_raises(tmp_path):
    body = """
        schema_version: "1.0.0"
        root_packages: [pkg]
        components: {}
    """
    with pytest.raises(ManifestError, match="at least one component"):
        load_manifest(_write(tmp_path, body))
