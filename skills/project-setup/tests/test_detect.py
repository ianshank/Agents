"""Unit tests for deterministic project detection (``makegen.detect``)."""

from __future__ import annotations

from pathlib import Path

from makegen import detect


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------- package managers
def test_pip_with_dev_extra_and_src_layout(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[build-system]\nrequires=["setuptools"]\n'
        '[project]\nname="demo-app"\nversion="0"\n'
        '[project.optional-dependencies]\ndev=["pytest","ruff","mypy","pytest-cov"]\n'
        "[tool.ruff]\n[tool.mypy]\n[tool.pytest.ini_options]\n"
        '[tool.coverage.run]\nsource=["demo_app"]\n[tool.coverage.report]\nfail_under=90\n',
    )
    _write(tmp_path, "src/demo_app/__init__.py")
    facts = detect(tmp_path)
    assert facts.package_manager == "pip"
    assert facts.install_cmd == '$(PIP) install -e ".[dev]"'
    assert facts.src_layout is True
    assert facts.type_checker == "mypy"
    assert facts.typecheck_paths == "src"
    assert facts.has_ruff and facts.has_pytest and facts.has_pytest_cov
    assert facts.coverage_source == "demo_app"
    assert facts.cov_fail_under == 90
    assert facts.has_build_backend is True


def test_poetry_via_tool_table(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.poetry]\nname="x"\n')
    facts = detect(tmp_path)
    assert facts.package_manager == "poetry"
    assert facts.install_cmd == "poetry install"


def test_poetry_via_lockfile(tmp_path: Path) -> None:
    _write(tmp_path, "poetry.lock", "")
    assert detect(tmp_path).package_manager == "poetry"


def test_pdm_and_uv_and_hatch(tmp_path: Path) -> None:
    pdm = tmp_path / "pdm"
    uv = tmp_path / "uv"
    hatch = tmp_path / "hatch"
    _write(pdm, "pyproject.toml", "[tool.pdm]\n")
    _write(uv, "uv.lock", "")
    _write(hatch, "pyproject.toml", "[tool.hatch]\n")
    assert detect(pdm).package_manager == "pdm"
    assert detect(uv).package_manager == "uv"
    assert detect(hatch).package_manager == "hatch"


def test_requirements_only_project(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "requests\n")
    facts = detect(tmp_path)
    assert facts.install_cmd == "$(PIP) install -r requirements.txt"


def test_build_system_only_uses_editable_install(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[build-system]\nrequires=["setuptools"]\n')
    assert detect(tmp_path).install_cmd == "$(PIP) install -e ."


def test_empty_directory_falls_back(tmp_path: Path) -> None:
    facts = detect(tmp_path)
    assert facts.package_manager == "pip"
    assert facts.install_cmd == "$(PIP) install -e ."
    assert facts.type_checker is None
    assert facts.has_ruff is False


# ------------------------------------------------------------------ type checker
def test_pyright_detection(tmp_path: Path) -> None:
    _write(tmp_path, "pyrightconfig.json", "{}")
    facts = detect(tmp_path)
    assert facts.type_checker == "pyright"
    assert facts.typecheck_paths == "."


def test_mypy_ini_detection(tmp_path: Path) -> None:
    _write(tmp_path, "mypy.ini", "[mypy]\n")
    assert detect(tmp_path).type_checker == "mypy"


# ------------------------------------------------------------------------- ruff
def test_ruff_via_config_file(tmp_path: Path) -> None:
    _write(tmp_path, "ruff.toml", "line-length=100\n")
    assert detect(tmp_path).has_ruff is True


# ---------------------------------------------------------------------- pytest
def test_pytest_via_tests_dir(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_x.py", "")
    assert detect(tmp_path).has_pytest is True


# --------------------------------------------------------------- coverage source
def test_coverage_source_guessed_from_src_package(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n")
    _write(tmp_path, "src/mypkg/__init__.py")
    assert detect(tmp_path).coverage_source == "mypkg"


def test_coverage_source_guessed_from_project_name(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname="my-lib"\n[tool.coverage.run]\nbranch=true\n')
    assert detect(tmp_path).coverage_source == "my_lib"


def test_coverage_source_dot_when_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n")
    assert detect(tmp_path).coverage_source == "."


def test_coverage_source_as_string(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.run]\nsource="single"\n')
    assert detect(tmp_path).coverage_source == "single"


def test_coverage_source_src_dir_without_package_falls_back_to_name(tmp_path: Path) -> None:
    # src/ exists (src_layout) but holds no package, so the guess falls through to the name.
    _write(tmp_path, "pyproject.toml", '[project]\nname="named"\n[tool.coverage.run]\nbranch=true\n')
    _write(tmp_path, "src/notapackage.txt", "x")
    facts = detect(tmp_path)
    assert facts.src_layout is True
    assert facts.coverage_source == "named"


# -------------------------------------------------------- composition detection
def test_detects_sibling_scripts(tmp_path: Path) -> None:
    _write(tmp_path, "scripts/quality-gate.sh", "#!/usr/bin/env bash\n")
    _write(tmp_path, "scripts/deploy.sh", "#!/usr/bin/env bash\n")
    facts = detect(tmp_path)
    assert facts.has_quality_gate_script is True
    assert facts.has_deploy_script is True


# ------------------------------------------------------------- malformed input
def test_malformed_pyproject_degrades_to_defaults(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "this is : not valid = toml [[[")
    facts = detect(tmp_path)
    assert facts.package_manager == "pip"
    assert facts.has_ruff is False


# ------------------------------------------------------- pytest-cov (never fabricate)
def test_pytest_cov_requires_declared_plugin(tmp_path: Path) -> None:
    # [tool.coverage] alone (standalone coverage.py) must NOT imply pytest-cov, else the
    # Makefile would fabricate a `pytest --cov` target that fails without the plugin.
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n[tool.pytest.ini_options]\n")
    facts = detect(tmp_path)
    assert facts.has_pytest is True
    assert facts.has_pytest_cov is False


def test_pytest_cov_from_dependency_groups(tmp_path: Path) -> None:
    # PEP 735 [dependency-groups]; the include-group dict entry is skipped without error.
    _write(
        tmp_path,
        "pyproject.toml",
        '[dependency-groups]\nall = [{include-group = "test"}]\ntest = ["pytest", "pytest-cov"]\n',
    )
    assert detect(tmp_path).has_pytest_cov is True


# -------------------------------------------------------------- fail_under coercion
def test_fail_under_accepts_string(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.report]\nfail_under = "87"\n')
    assert detect(tmp_path).cov_fail_under == 87


def test_fail_under_unparseable_defaults_zero(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.report]\nfail_under = "lots"\n')
    assert detect(tmp_path).cov_fail_under == 0
