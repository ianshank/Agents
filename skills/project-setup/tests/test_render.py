"""Unit tests for deterministic Makefile rendering (``makegen.render``)."""

from __future__ import annotations

from makegen import ProjectFacts, render_makefile


def _recipe_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln[:1] == "\t"]


FULL = ProjectFacts(
    has_ruff=True,
    type_checker="mypy",
    typecheck_paths="src",
    has_pytest=True,
    has_pytest_cov=True,
    coverage_source="demo",
    cov_fail_under=90,
    src_layout=True,
    has_build_backend=True,
)


def test_full_project_emits_all_targets() -> None:
    out = render_makefile(FULL)
    for target in (
        "help:",
        "install:",
        "format:",
        "lint:",
        "typecheck:",
        "test:",
        "coverage:",
        "check:",
        "build:",
        "clean:",
    ):
        assert target in out
    assert ".DEFAULT_GOAL := help" in out
    assert ".DELETE_ON_ERROR:" in out
    assert ".PHONY:" in out


def test_every_recipe_line_is_tab_indented() -> None:
    out = render_makefile(FULL)
    recipes = _recipe_lines(out)
    assert recipes, "expected recipe lines"
    assert all(ln.startswith("\t") for ln in recipes)
    # And no recipe was emitted with leading spaces (the classic Make footgun).
    assert not any(ln.startswith("    ") and ("ruff" in ln or "pytest" in ln) for ln in out.splitlines())


def test_output_ends_with_single_newline_and_is_deterministic() -> None:
    out = render_makefile(FULL)
    assert out.endswith("\n") and not out.endswith("\n\n")
    assert render_makefile(FULL) == out  # byte-stable


def test_check_lists_existing_prereqs() -> None:
    out = render_makefile(FULL)
    assert "check: lint typecheck test ## " in out


def test_variables_emitted_only_when_used() -> None:
    out = render_makefile(FULL)
    assert "TYPECHECK_PATHS ?= src" in out
    assert "COVERAGE_SOURCE ?= demo" in out
    assert "COV_FAIL_UNDER ?= 90" in out


def test_delegation_when_quality_gate_present() -> None:
    facts = ProjectFacts(
        has_ruff=True,
        type_checker="mypy",
        has_pytest=True,
        has_pytest_cov=True,
        has_quality_gate_script=True,
    )
    out = render_makefile(facts)
    assert "./scripts/quality-gate.sh lint" in out
    assert "./scripts/quality-gate.sh typecheck" in out
    assert "./scripts/quality-gate.sh test" in out
    assert "./scripts/quality-gate.sh coverage" in out
    assert "check: ## Run the full quality gate" in out
    assert "./scripts/quality-gate.sh all" in out
    # Inline tool variables are not emitted in delegation mode.
    assert "TYPECHECK_PATHS" not in out
    assert "COVERAGE_SOURCE" not in out


def test_minimal_project_omits_absent_targets() -> None:
    out = render_makefile(ProjectFacts())
    assert "help:" in out and "install:" in out and "clean:" in out
    for absent in ("lint:", "typecheck:", "test:", "coverage:", "check:", "build:", "format:", "deploy:"):
        assert absent not in out


def test_pyright_target() -> None:
    out = render_makefile(ProjectFacts(type_checker="pyright", typecheck_paths="."))
    assert "pyright $(TYPECHECK_PATHS)" in out


def test_deploy_target_when_script_present() -> None:
    out = render_makefile(ProjectFacts(has_deploy_script=True))
    assert "deploy: ## " in out
    assert "./scripts/deploy.sh release" in out


def test_check_with_single_prereq() -> None:
    out = render_makefile(ProjectFacts(has_pytest=True))
    assert "check: test ## " in out


def test_no_check_when_nothing_to_gate() -> None:
    out = render_makefile(ProjectFacts(has_build_backend=True))
    assert "check:" not in out
    assert "build:" in out


def test_no_pip_variable_for_non_pip_install() -> None:
    # A manager whose install command does not reference $(PIP) must not emit the PIP var.
    out = render_makefile(ProjectFacts(package_manager="poetry", install_cmd="poetry install"))
    assert "PIP ?=" not in out
    assert "poetry install" in out


def test_delegation_omits_absent_tools() -> None:
    # Never fabricate: with a gate script present but only ruff configured, only `lint`
    # delegates; typecheck/test/coverage are omitted (the gate script would not implement them).
    out = render_makefile(ProjectFacts(has_ruff=True, has_quality_gate_script=True))
    assert "./scripts/quality-gate.sh lint" in out
    assert "quality-gate.sh typecheck" not in out
    assert "quality-gate.sh test" not in out
    assert "quality-gate.sh coverage" not in out
    assert "./scripts/quality-gate.sh all" in out  # check still delegates to the aggregate
