"""End-to-end tests driving the thin runners as subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
FIXTURES = os.path.join(HERE, "fixtures")
DRIFT_CHECK = os.path.join(SCRIPTS, "drift_check.py")
MERMAID_GEN = os.path.join(SCRIPTS, "mermaid_gen.py")


def _run(script, *args):
    return subprocess.run(
        [sys.executable, script, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _manifest(tmp_path, *, fixture_sub, pkg, dependencies: str) -> str:
    # Forward slashes: this path is embedded in a YAML double-quoted scalar, where a
    # Windows backslash path (C:\Users\...) is parsed as invalid escape sequences.
    # Forward slashes are valid YAML and accepted on sys.path on every platform.
    src_dir = os.path.join(FIXTURES, fixture_sub).replace("\\", "/")
    body = textwrap.dedent(
        f"""
        schema_version: "1.0.0"
        root_packages: [{pkg}]
        sys_path: ["{src_dir}"]
        components:
          api: [{pkg}.api]
          core: [{pkg}.core]
        dependencies:
        {dependencies}
        """
    )
    path = tmp_path / "architecture.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_drift_clean_exits_zero(tmp_path):
    manifest = _manifest(tmp_path, fixture_sub="clean_pkg", pkg="clnpkg", dependencies="  api: [core]")
    result = _run(DRIFT_CHECK, "--manifest", manifest)
    assert result.returncode == 0, result.stderr
    assert "matches the manifest" in result.stdout


def test_drift_detected_exits_one(tmp_path):
    # drfpkg has a core -> api back-edge that the manifest does not declare.
    manifest = _manifest(tmp_path, fixture_sub="drift_pkg", pkg="drfpkg", dependencies="  api: [core]")
    result = _run(DRIFT_CHECK, "--manifest", manifest)
    assert result.returncode == 1
    assert "core -> api" in result.stderr


def test_emit_actual_prints_dependencies(tmp_path):
    manifest = _manifest(tmp_path, fixture_sub="clean_pkg", pkg="clnpkg", dependencies="  api: [core]")
    result = _run(DRIFT_CHECK, "--manifest", manifest, "--emit-actual")
    assert result.returncode == 0
    assert "dependencies:" in result.stdout
    assert "api:" in result.stdout


def test_bad_manifest_exits_two(tmp_path):
    path = tmp_path / "architecture.yaml"
    path.write_text('schema_version: "1.0.0"\nroot_packages: []\ncomponents: {a: [x]}\n', encoding="utf-8")
    result = _run(DRIFT_CHECK, "--manifest", str(path))
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_mermaid_generate_then_check_roundtrip(tmp_path):
    manifest = _manifest(tmp_path, fixture_sub="clean_pkg", pkg="clnpkg", dependencies="  api: [core]")
    out = tmp_path / "architecture.mmd"
    gen = _run(MERMAID_GEN, "--manifest", manifest, "-o", str(out))
    assert gen.returncode == 0, gen.stderr
    assert out.is_file()
    assert "C4Component" in out.read_text(encoding="utf-8")

    check = _run(MERMAID_GEN, "--manifest", manifest, "--check", "-o", str(out))
    assert check.returncode == 0, check.stderr


def test_mermaid_check_fails_when_stale(tmp_path):
    manifest = _manifest(tmp_path, fixture_sub="clean_pkg", pkg="clnpkg", dependencies="  api: [core]")
    out = tmp_path / "architecture.mmd"
    _run(MERMAID_GEN, "--manifest", manifest, "-o", str(out))
    out.write_text("C4Component\n    title tampered\n", encoding="utf-8")
    check = _run(MERMAID_GEN, "--manifest", manifest, "--check", "-o", str(out))
    assert check.returncode == 1
    assert "stale" in check.stderr


def test_mermaid_check_missing_file_fails(tmp_path):
    manifest = _manifest(tmp_path, fixture_sub="clean_pkg", pkg="clnpkg", dependencies="  api: [core]")
    missing = tmp_path / "nope.mmd"
    check = _run(MERMAID_GEN, "--manifest", manifest, "--check", "-o", str(missing))
    assert check.returncode == 1
    assert "missing" in check.stderr


@pytest.mark.parametrize("script", [DRIFT_CHECK, MERMAID_GEN])
def test_runner_manifest_not_found_exits_two(tmp_path, script):
    result = _run(script, "--manifest", str(tmp_path / "absent.yaml"))
    assert result.returncode == 2


def test_relative_sys_path_resolves_against_manifest_dir(tmp_path):
    """Portability: a manifest with a relative sys_path works from any cwd."""
    proj = tmp_path / "proj"
    pkg = proj / "relpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "api.py").write_text("from . import core\n", encoding="utf-8")
    (proj / "architecture.yaml").write_text(
        textwrap.dedent(
            """
            schema_version: "1.0.0"
            root_packages: [relpkg]
            sys_path: ["."]
            components:
              api: [relpkg.api]
              core: [relpkg.core]
            dependencies:
              api: [core]
            """
        ),
        encoding="utf-8",
    )
    # Run from an unrelated cwd; the relative sys_path must resolve against the
    # manifest's directory, not the cwd.
    result = subprocess.run(
        [sys.executable, DRIFT_CHECK, "--manifest", str(proj / "architecture.yaml")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
