"""Unit tests for deterministic gate detection (``gategen.detect``)."""

from __future__ import annotations

from pathlib import Path

from gategen import detect


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_full_toolchain_src_layout(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname="demo"\n'
        '[project.optional-dependencies]\ndev=["pytest-cov"]\n'
        "[tool.ruff]\n[tool.mypy]\n[tool.pytest.ini_options]\n"
        '[tool.coverage.run]\nsource=["demo"]\n[tool.coverage.report]\nfail_under=88\n',
    )
    _write(tmp_path, "src/demo/__init__.py")
    facts = detect(tmp_path)
    assert facts.has_ruff and facts.has_pytest and facts.has_pytest_cov
    assert facts.type_checker == "mypy"
    assert facts.typecheck_paths == "src"
    assert facts.coverage_source == "demo"
    assert facts.cov_fail_under == 88
    assert facts.has_any_step is True


def test_empty_project_has_no_steps(tmp_path: Path) -> None:
    facts = detect(tmp_path)
    assert facts.has_ruff is False
    assert facts.type_checker is None
    assert facts.has_pytest is False
    assert facts.has_any_step is False


def test_ruff_via_config_file(tmp_path: Path) -> None:
    _write(tmp_path, "ruff.toml", "line-length=100\n")
    assert detect(tmp_path).has_ruff is True


def test_pyright_detection(tmp_path: Path) -> None:
    _write(tmp_path, "pyrightconfig.json", "{}")
    facts = detect(tmp_path)
    assert facts.type_checker == "pyright"
    assert facts.typecheck_paths == "."


def test_mypy_ini_detection(tmp_path: Path) -> None:
    _write(tmp_path, "mypy.ini", "[mypy]\n")
    assert detect(tmp_path).type_checker == "mypy"


def test_pytest_via_tests_dir(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_x.py", "")
    assert detect(tmp_path).has_pytest is True


def test_pytest_cov_via_dependency(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname="d"\n[project.optional-dependencies]\ndev=["pytest-cov>=5"]\n',
    )
    assert detect(tmp_path).has_pytest_cov is True


def test_coverage_source_as_string(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.run]\nsource="single"\n')
    assert detect(tmp_path).coverage_source == "single"


def test_coverage_source_guessed_from_name(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname="my-lib"\n[tool.coverage.run]\nbranch=true\n')
    assert detect(tmp_path).coverage_source == "my_lib"


def test_coverage_source_from_src_package(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n")
    _write(tmp_path, "src/pkg/__init__.py")
    assert detect(tmp_path).coverage_source == "pkg"


def test_coverage_source_src_without_package(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname="named"\n[tool.coverage.run]\nbranch=true\n')
    _write(tmp_path, "src/notapackage.txt", "x")
    assert detect(tmp_path).coverage_source == "named"


def test_coverage_source_dot_when_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n")
    assert detect(tmp_path).coverage_source == "."


def test_malformed_pyproject_degrades(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", "not valid = toml [[[")
    facts = detect(tmp_path)
    assert facts.has_ruff is False
    assert facts.has_any_step is False


def test_pytest_cov_requires_declared_plugin(tmp_path: Path) -> None:
    # [tool.coverage] alone must NOT imply pytest-cov (never fabricate a `pytest --cov` gate step).
    _write(tmp_path, "pyproject.toml", "[tool.coverage.run]\nbranch=true\n[tool.pytest.ini_options]\n")
    assert detect(tmp_path).has_pytest_cov is False


def test_pytest_cov_from_dependency_groups(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[dependency-groups]\nall = [{include-group = "test"}]\ntest = ["pytest-cov"]\n',
    )
    assert detect(tmp_path).has_pytest_cov is True


def test_coverage_only_still_counts_as_a_step(tmp_path: Path) -> None:
    # A project with pytest-cov but no pytest table still has an emittable coverage step.
    _write(tmp_path, "pyproject.toml", '[project.optional-dependencies]\ndev=["pytest-cov"]\n')
    facts = detect(tmp_path)
    assert facts.has_pytest is False
    assert facts.has_pytest_cov is True
    assert facts.has_any_step is True


def test_fail_under_accepts_string(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.report]\nfail_under = "82"\n')
    assert detect(tmp_path).cov_fail_under == 82


def test_fail_under_unparseable_defaults_zero(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[tool.coverage.report]\nfail_under = "n/a"\n')
    assert detect(tmp_path).cov_fail_under == 0
