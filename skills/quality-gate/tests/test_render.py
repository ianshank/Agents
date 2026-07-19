"""Unit tests for deterministic gate-script rendering (``gategen.render``)."""

from __future__ import annotations

from gategen import MARKER, GateFacts, render_ci_snippet, render_gate, split_at_marker

FULL = GateFacts(
    has_ruff=True,
    type_checker="mypy",
    typecheck_paths="src",
    has_pytest=True,
    has_pytest_cov=True,
    coverage_source="demo",
    cov_fail_under=90,
)


def test_header_and_strict_mode() -> None:
    out = render_gate(FULL)
    assert out.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in out
    assert out.endswith("\n") and not out.endswith("\n\n")


def test_all_steps_and_dispatch() -> None:
    out = render_gate(FULL)
    for fn in ("do_lint()", "do_typecheck()", "do_test()", "do_coverage()", "do_all()", "main()"):
        assert fn in out
    for arm in ("lint) do_lint", "typecheck) do_typecheck", "test) do_test", "coverage) do_coverage", "all) do_all"):
        assert arm in out
    assert 'main "$@"' in out


def test_variables_are_overridable_and_quoted() -> None:
    out = render_gate(FULL)
    assert 'PYTHON="${PYTHON:-python3}"' in out
    assert 'TYPECHECK_PATHS="${TYPECHECK_PATHS:-src}"' in out
    assert 'COVERAGE_SOURCE="${COVERAGE_SOURCE:-demo}"' in out
    assert 'COV_FAIL_UNDER="${COV_FAIL_UNDER:-90}"' in out
    # ShellCheck-cleanliness: every variable expansion in commands is double-quoted.
    assert '"$PYTHON" -m ruff check "."' in out
    assert '--cov="$COVERAGE_SOURCE"' in out


def test_all_runs_coverage_not_test_when_both_present() -> None:
    # coverage runs the tests too; do_all must not run them twice.
    out = render_gate(FULL)
    do_all = out.split("do_all() {")[1].split("}")[0]
    assert "do_coverage" in do_all
    assert "do_test" not in do_all
    assert 'log "PASS"' in do_all


def test_all_runs_test_when_no_coverage() -> None:
    out = render_gate(GateFacts(has_ruff=True, has_pytest=True))
    do_all = out.split("do_all() {")[1].split("}")[0]
    assert "do_test" in do_all
    assert "do_coverage" not in do_all


def test_pyright_step() -> None:
    out = render_gate(GateFacts(type_checker="pyright", typecheck_paths="."))
    assert 'pyright "$TYPECHECK_PATHS"' in out


def test_only_present_steps_are_emitted() -> None:
    out = render_gate(GateFacts(has_ruff=True))
    assert "do_lint()" in out
    for absent in ("do_typecheck()", "do_test()", "do_coverage()"):
        assert absent not in out
    assert "usage: $0 [lint|all]" in out


def test_empty_facts_produce_noop_gate() -> None:
    out = render_gate(GateFacts())
    assert "do_all()" in out and 'log "PASS"' in out
    assert "do_lint()" not in out
    assert "usage: $0 [all]" in out


def test_deterministic() -> None:
    assert render_gate(FULL) == render_gate(FULL)


def test_ci_snippet_runs_same_script() -> None:
    snippet = render_ci_snippet()
    assert "./scripts/quality-gate.sh all" in snippet
    assert snippet.endswith("\n")


def test_header_usage_references_scripts_path() -> None:
    # The script is written to scripts/quality-gate.sh, so the header must not mislead.
    out = render_gate(FULL)
    assert "# Usage: ./scripts/quality-gate.sh [lint|typecheck|test|coverage|all]" in out


def test_special_chars_in_source_are_shell_escaped() -> None:
    # A detected value containing $ must be neutralised inside the ${VAR:-...} default.
    out = render_gate(GateFacts(has_pytest_cov=True, coverage_source="pkg$x"))
    assert 'COVERAGE_SOURCE="${COVERAGE_SOURCE:-pkg\\$x}"' in out


# ------------------------------------------------------------ 1.1.0: tuples & BC
def test_str_fields_coerce_to_tuples_for_backwards_compat() -> None:
    facts = GateFacts(typecheck_paths="src", coverage_source="demo", lint_paths="pkg")
    assert facts.typecheck_paths == ("src",)
    assert facts.coverage_source == ("demo",)
    assert facts.lint_paths == ("pkg",)


def test_multi_typecheck_paths_render_one_invocation_each() -> None:
    out = render_gate(GateFacts(type_checker="mypy", typecheck_paths=("src/pkg", "scripts", "tests")))
    assert '"$PYTHON" -m mypy "src/pkg"' in out
    assert '"$PYTHON" -m mypy "scripts"' in out
    assert '"$PYTHON" -m mypy "tests"' in out
    # The single-path env-var DEFINITION cannot hold a list; it must not be emitted here —
    # but a notice line must warn when an exported override would be silently swallowed.
    assert 'TYPECHECK_PATHS="${TYPECHECK_PATHS:-' not in out
    assert "TYPECHECK_PATHS is ignored" in out


def test_multi_coverage_sources_render_repeated_cov_flags() -> None:
    out = render_gate(GateFacts(has_pytest_cov=True, coverage_source=("pkg_a", "pkg_b"), cov_fail_under=85))
    assert '--cov="pkg_a" --cov="pkg_b"' in out
    assert 'COVERAGE_SOURCE="${COVERAGE_SOURCE:-' not in out  # no single-source env var in multi mode
    assert "COVERAGE_SOURCE is ignored" in out  # ...and the swallowed override warns
    assert 'COV_FAIL_UNDER="${COV_FAIL_UNDER:-85}"' in out  # threshold override survives


def test_single_path_forms_have_no_ignored_notice() -> None:
    out = render_gate(FULL)  # single typecheck path + single coverage source
    assert "is ignored" not in out


def test_lint_paths_render_quoted_targets() -> None:
    out = render_gate(GateFacts(has_ruff=True, lint_paths=("src", "tests", "scripts")))
    assert '"$PYTHON" -m ruff check "src" "tests" "scripts"' in out
    assert '"$PYTHON" -m ruff format --check "src" "tests" "scripts"' in out


def test_default_lint_is_whole_tree() -> None:
    out = render_gate(GateFacts(has_ruff=True))
    assert '"$PYTHON" -m ruff check "."' in out  # uniform quoted-tuple form


def test_empty_lint_paths_normalize_to_whole_tree() -> None:
    facts = GateFacts(has_ruff=True, lint_paths=())
    assert facts.lint_paths == (".",)  # uniform with the other tuple fields


# ------------------------------------------------- 1.1.0: marker, hook, provenance
def test_marker_and_default_tail_present() -> None:
    out = render_gate(FULL)
    assert MARKER in out
    prefix, tail = split_at_marker(out)
    assert prefix.endswith(MARKER + "\n")
    assert 'main "$@"' in tail  # dispatch lives below the marker (hand region)
    assert "do_extra()" in tail  # seam documentation


def test_do_all_invokes_do_extra_hook_when_defined() -> None:
    out = render_gate(FULL)
    do_all = out.split("do_all() {")[1].split("}")[0]
    assert "declare -F do_extra" in do_all
    assert "do_extra" in do_all


def test_regen_provenance_line_embedded_when_args_given() -> None:
    out = render_gate(FULL, regen_args=("--root", ".", "--lint-path", "src"))
    assert "# regenerate: python scripts/gen_gate.py --root . --lint-path src" in out
    # Provenance is part of the generator-owned prefix (freshness-checked).
    prefix, _ = split_at_marker(out)
    assert "# regenerate:" in prefix


def test_no_provenance_line_without_args() -> None:
    assert "# regenerate:" not in render_gate(FULL)


def test_split_at_marker_without_marker_is_all_prefix() -> None:
    prefix, tail = split_at_marker("no marker here\n")
    assert prefix == "no marker here\n" and tail == ""


def test_split_at_marker_handles_crlf_line_endings() -> None:
    # A Windows-edited artifact must not yield a tail starting with a stray \r (that would
    # corrupt tail preservation into mixed line endings and cause false drift).
    text = "line one\r\n" + MARKER + "\r\nhand content\r\n"
    prefix, tail = split_at_marker(text)
    assert prefix.endswith(MARKER + "\r\n")
    assert tail == "hand content\r\n"


def test_multi_path_pyright_renders_single_invocation() -> None:
    # Unlike mypy (deliberate per-path runs), pyright takes all paths at once so its
    # startup cost is paid once, not once per path.
    out = render_gate(GateFacts(type_checker="pyright", typecheck_paths=("src", "tests")))
    assert 'pyright "src" "tests"' in out
    assert sum(line.strip().startswith("pyright ") for line in out.splitlines()) == 1


def test_regen_program_is_embedded_as_given() -> None:
    # The program path is recorded AS INVOKED (cwd-relative, like --root) so the line replays.
    out = render_gate(FULL, regen_args=("--root", "."), regen_program="skills/quality-gate/scripts/gen_gate.py")
    assert "# regenerate: python skills/quality-gate/scripts/gen_gate.py --root ." in out


def test_provenance_args_are_shell_quoted() -> None:
    # A path with a space must stay copy-paste reproducible in the regenerate comment.
    out = render_gate(FULL, regen_args=("--root", ".", "--lint-path", "my dir"))
    assert "# regenerate: python scripts/gen_gate.py --root . --lint-path 'my dir'" in out


def test_provenance_omitted_for_control_chars() -> None:
    # A newline inside a quoted arg would escape the comment into executable script text;
    # such an invocation is unrepresentable on one line, so no provenance is emitted.
    out = render_gate(FULL, regen_args=("--root", ".", "--lint-path", "evil\ninjected"))
    assert "# regenerate:" not in out
    assert "injected" not in out


def test_positional_construction_matches_1_0_field_order() -> None:
    # 1.0.x positional callers: (python, has_ruff, type_checker, typecheck_paths,
    # has_pytest, has_pytest_cov, coverage_source, cov_fail_under). New fields append.
    facts = GateFacts("python3", True, "mypy", "src", True, True, "demo", 90)
    assert facts.has_ruff is True and facts.type_checker == "mypy"
    assert facts.typecheck_paths == ("src",) and facts.coverage_source == ("demo",)
    assert facts.cov_fail_under == 90 and facts.lint_paths == (".",)  # appended field, whole-tree default


def test_empty_tuples_normalize_to_whole_tree_defaults() -> None:
    # An empty collection would render a step with no commands (a no-op that "passes").
    facts = GateFacts(type_checker="mypy", typecheck_paths=(), has_pytest_cov=True, coverage_source=())
    assert facts.typecheck_paths == (".",) and facts.coverage_source == (".",)
    out = render_gate(facts)
    assert '"$PYTHON" -m mypy "$TYPECHECK_PATHS"' in out  # real command, not an empty body
