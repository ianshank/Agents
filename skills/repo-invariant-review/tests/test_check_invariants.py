"""Unit tests for the invariant checker.

Each test pins one check against a purpose-built fixture repo, so a check that silently
stops firing fails here rather than in a PR that should have been blocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_fixture import build
from check_invariants import (
    Finding,
    Report,
    _matches_protected,
    main,
    render_text,
    review,
)


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    return build("clean", tmp_path / "clean")


@pytest.fixture
def violating_repo(tmp_path: Path) -> Path:
    return build("violating", tmp_path / "violating")


# --- protected paths ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("features.yaml", "features.yaml", True),
        ("tests/test_x.py", "tests/**", True),
        ("tests/deep/nested/test_x.py", "tests/**", True),
        ("src/eval_harness/scorers/a.py", "src/eval_harness/scorers/", True),
        ("docs/notes.md", "tests/**", False),
        ("testsuite/x.py", "tests/**", False),  # prefix must be a path boundary
        ("anything", "**", False),  # a metacharacter-only pattern matches nothing
    ],
)
def test_protected_matching_handles_globs_and_boundaries(path, pattern, expected):
    assert _matches_protected(path, pattern) is expected


def test_the_repos_own_matcher_is_loaded_when_present(violating_repo: Path):
    """The skill must match with the guard's code, not an approximation of it."""
    from check_invariants import _real_matcher

    matcher = _real_matcher(violating_repo)
    assert matcher is not None
    assert matcher("tests/test_x.py") is True
    assert matcher("docs/notes.md") is False


def test_real_matcher_catches_the_mid_path_glob_the_fallback_silently_misses(violating_repo: Path):
    """The regression this import exists to prevent.

    ``skills/*/tests/**`` strips to ``/tests`` under prefix matching, which matches nothing
    — a false *negative*, so the skill would report "no protected files" for a change CI
    still blocks. Asserting both directions keeps the fallback honest about being weaker.
    """
    from check_invariants import _real_matcher

    path, pattern = "skills/foo/tests/test_x.py", "skills/*/tests/**"
    matcher = _real_matcher(violating_repo)
    assert matcher is not None

    assert matcher(path) is True, "the real guard protects this path"
    assert _matches_protected(path, pattern) is False, "the fallback misses it — the divergence being closed"


def test_protected_finding_uses_the_real_matcher_end_to_end(violating_repo: Path):
    """A mid-path-glob hit must reach the finding, not just the matcher."""
    from check_invariants import check_protected_paths

    findings = check_protected_paths(violating_repo, ["skills/foo/tests/test_x.py"], has_label=False)
    assert findings, "the real guard protects this path, so the check must fire"
    assert "skills/foo/tests/test_x.py" in findings[0].detail


def test_fixture_guard_normalises_paths_the_way_the_real_one_does(violating_repo: Path):
    """The stub must not be laxer than the guard it stands in for.

    `lstrip("./")` strips any leading "." or "/" character rather than the "./" prefix, so
    "../features.yaml" would normalise to "features.yaml" and match a pattern the real
    guard does not — a fixture that answers differently from the guard silently weakens
    every test built on it.
    """
    matcher = _real_matcher_or_skip(violating_repo)

    assert matcher("features.yaml") is True
    assert matcher("./features.yaml") is True, "a './' prefix is stripped, as the guard does"
    assert matcher("../features.yaml") is False, "'../' is not a './' prefix and must not be stripped"


def _real_matcher_or_skip(repo: Path):
    from check_invariants import _real_matcher

    matcher = _real_matcher(repo)
    assert matcher is not None
    return matcher


def test_real_matcher_is_absent_outside_the_repo(tmp_path: Path):
    """No guard module (running the skill on some other tree) → fall back, don't crash."""
    from check_invariants import _real_matcher

    assert _real_matcher(tmp_path) is None


def test_real_matcher_is_absent_when_the_guard_predates_is_protected(violating_repo: Path):
    """Backward compatibility: an older guard exposing only PROTECTED_PATTERNS."""
    from check_invariants import _real_matcher

    (violating_repo / "scripts" / "eval_protected_paths.py").write_text(
        'PROTECTED_PATTERNS = ("features.yaml",)\n', encoding="utf-8"
    )
    assert _real_matcher(violating_repo) is None


def test_real_matcher_is_absent_when_no_import_spec_can_be_built(violating_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """Defensive branch: importlib declining to produce a spec must degrade, not raise."""
    import check_invariants

    monkeypatch.setattr(check_invariants.importlib.util, "spec_from_file_location", lambda *a, **k: None)
    assert check_invariants._real_matcher(violating_repo) is None


def test_loading_the_guard_does_not_write_bytecode_into_the_reviewed_tree(violating_repo: Path):
    """Executing the guard must leave no trace: __pycache__ would land in `changed_files`
    and break the byte-stability contract on the second run."""
    from check_invariants import _real_matcher

    assert _real_matcher(violating_repo) is not None
    assert not (violating_repo / "scripts" / "__pycache__").exists()


def test_falls_back_to_prefix_matching_when_the_guard_is_unloadable(violating_repo: Path):
    """A syntactically broken guard must degrade to the fallback, never crash the skill."""
    from check_invariants import _real_matcher

    (violating_repo / "scripts" / "eval_protected_paths.py").write_text("def (\n", encoding="utf-8")
    assert _real_matcher(violating_repo) is None

    report = review(violating_repo, "HEAD", has_label=False)
    assert [f for f in report.findings if f.check == "protected_paths"]


def test_protected_paths_fire_on_a_violating_tree(violating_repo: Path):
    report = review(violating_repo, "HEAD", has_label=False)
    hits = [f for f in report.findings if f.check == "protected_paths"]
    assert hits and "features.yaml" in hits[0].detail


def test_the_label_suppresses_the_protected_finding(violating_repo: Path):
    """So it stops masking the findings a reviewer still has to act on."""
    report = review(violating_repo, "HEAD", has_label=True)
    assert not [f for f in report.findings if f.check == "protected_paths"]
    assert report.blocking, "other collisions must still block"


# --- the other checks --------------------------------------------------------------


def test_size_budget_fires_over_the_ceiling(violating_repo: Path):
    hits = [f for f in review(violating_repo, "HEAD", False).findings if f.check == "size_budget"]
    assert hits and "601 lines" in hits[0].detail


def test_airgap_fires_on_a_forbidden_import(violating_repo: Path):
    hits = [f for f in review(violating_repo, "HEAD", False).findings if f.check == "airgap"]
    assert hits and "flow_corpus" in hits[0].detail


def test_baseline_findings_are_advisory_not_blocking(violating_repo: Path):
    baselines = [f for f in review(violating_repo, "HEAD", False).findings if "baselines" in f.check]
    assert baselines and all(not f.blocking for f in baselines)


def test_a_clean_tree_reports_nothing_blocking(clean_repo: Path):
    report = review(clean_repo, "HEAD", has_label=False)
    assert not report.blocking


def test_core_model_change_requires_an_adr(tmp_path: Path):
    repo = build("clean", tmp_path / "core")
    (repo / "src" / "eval_harness" / "core").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "eval_harness" / "core" / "types.py").write_text("x = 1\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    hits = [f for f in review(repo, "HEAD", False).findings if f.check == "core_model_change"]
    assert hits and "CHARTER" in hits[0].remedy


def test_an_adr_in_the_same_change_satisfies_the_core_model_check(tmp_path: Path):
    repo = build("clean", tmp_path / "core_adr")
    (repo / "src" / "eval_harness" / "core").mkdir(parents=True, exist_ok=True)
    (repo / "src" / "eval_harness" / "core" / "types.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "docs" / "decisions").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "decisions" / "0001-x.md").write_text("# 0001\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    assert not [f for f in review(repo, "HEAD", False).findings if f.check == "core_model_change"]


# --- report shape ------------------------------------------------------------------


def test_the_report_is_byte_stable_for_the_same_input(violating_repo: Path):
    first = json.dumps(review(violating_repo, "HEAD", False).to_dict(), sort_keys=True, indent=2)
    second = json.dumps(review(violating_repo, "HEAD", False).to_dict(), sort_keys=True, indent=2)
    assert first == second


def test_the_report_carries_no_absolute_paths(violating_repo: Path):
    """Reports are committable, so they must not leak the machine they were built on."""
    payload = json.dumps(review(violating_repo, "HEAD", False).to_dict())
    assert str(violating_repo) not in payload


def test_render_text_is_readable_when_clean():
    assert "OK" in render_text(Report(changed_files=["a.py"]))


def test_render_text_marks_blocking_and_advisory_distinctly():
    report = Report(findings=[Finding("a", "d1", "r1"), Finding("b", "d2", "r2", blocking=False)])
    rendered = render_text(report)
    assert "BLOCKING" in rendered and "advisory" in rendered


# --- CLI ---------------------------------------------------------------------------


def test_cli_exits_zero_on_a_clean_tree(clean_repo: Path, capsys):
    assert main(["--repo", str(clean_repo), "--base", "HEAD"]) == 0


def test_cli_exits_one_on_a_violating_tree(violating_repo: Path, capsys):
    assert main(["--repo", str(violating_repo), "--base", "HEAD"]) == 1


def test_cli_strict_promotes_advisory_findings(clean_repo: Path, tmp_path: Path, capsys):
    """A tree with only advisory findings passes normally and fails under --strict."""
    (clean_repo / "src").mkdir(exist_ok=True)
    (clean_repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=clean_repo, check=True, capture_output=True)
    assert main(["--repo", str(clean_repo), "--base", "HEAD"]) == 0
    assert main(["--repo", str(clean_repo), "--base", "HEAD", "--strict"]) == 1


def test_cli_rejects_a_non_repository(tmp_path: Path, capsys):
    assert main(["--repo", str(tmp_path), "--base", "HEAD"]) == 2


def test_cli_writes_a_json_report(violating_repo: Path, tmp_path: Path, capsys):
    out = tmp_path / "nested" / "report.json"
    main(["--repo", str(violating_repo), "--base", "HEAD", "--format", "json", "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is False
    assert {f["check"] for f in payload["findings"]} >= {"protected_paths", "size_budget", "airgap"}


# --- fallbacks and edge paths ------------------------------------------------------


def test_falls_back_to_bundled_patterns_outside_the_repo(tmp_path: Path):
    """The skill stays usable in a tree that has no eval_protected_paths.py."""
    from check_invariants import FALLBACK_PROTECTED, _protected_patterns

    assert _protected_patterns(tmp_path) == FALLBACK_PROTECTED


def test_falls_back_to_the_default_ceiling_when_the_gate_is_absent(tmp_path: Path):
    from check_invariants import DEFAULT_MAX_FILE_LINES, _max_file_lines

    assert _max_file_lines(tmp_path) == DEFAULT_MAX_FILE_LINES


def test_reads_the_real_ceiling_from_the_gate_when_present(violating_repo: Path):
    from check_invariants import _max_file_lines

    assert _max_file_lines(violating_repo) == 500


def test_falls_back_to_the_working_tree_when_the_base_ref_is_unknown(violating_repo: Path):
    """An unresolvable base must degrade to the porcelain diff, not to an empty review."""
    from check_invariants import changed_files

    assert changed_files(violating_repo, "refs/heads/does-not-exist")


def test_git_helper_returns_empty_on_failure(tmp_path: Path):
    from check_invariants import _run_git

    assert _run_git(["rev-parse", "HEAD"], tmp_path) == ""


def test_size_budget_ignores_non_python_and_deleted_files(violating_repo: Path):
    from check_invariants import check_size_budget

    assert check_size_budget(violating_repo, ["README.md", "gone.py"]) == []


def test_airgap_ignores_files_outside_the_guarded_packages(violating_repo: Path):
    from check_invariants import check_airgap

    (violating_repo / "unrelated.py").write_text("from flow_corpus import x\n", encoding="utf-8")
    assert check_airgap(violating_repo, ["unrelated.py"]) == []


def test_airgap_ignores_an_eval_harness_files_own_absolute_self_import(violating_repo: Path):
    """Regression: an eval_harness file importing another eval_harness module by its
    absolute name (``from eval_harness.x import y``, as opposed to a relative
    ``from .x import y``) is not a flow_corpus->eval_harness airgap crossing -- it is
    the same package importing itself. A prior version of the owner-membership check
    special-cased the "src/eval_harness" prefix in a way that applied it to BOTH
    airgap pairs, so this ordinary, common pattern was misdetected as a violation on
    the ``("flow_corpus", "eval_harness")`` pair even though the file has nothing to
    do with flow_corpus."""
    from check_invariants import check_airgap

    target = violating_repo / "src" / "eval_harness" / "agent_core_adapter" / "bridge.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("from eval_harness.core.interfaces import Judge\n", encoding="utf-8")
    assert check_airgap(violating_repo, ["src/eval_harness/agent_core_adapter/bridge.py"]) == []


def test_readme_drift_fires_when_a_registered_name_is_undocumented(violating_repo: Path):
    from check_invariants import check_readme_registry_drift

    scorer = violating_repo / "src" / "eval_harness" / "scorers" / "new.py"
    scorer.write_text('@SCORERS.register("brand_new")\nclass X: ...\n', encoding="utf-8")
    hits = check_readme_registry_drift(violating_repo, ["src/eval_harness/scorers/new.py"])
    assert hits and "brand_new" in hits[0].detail


def test_readme_drift_is_silent_when_scorers_are_untouched(violating_repo: Path):
    from check_invariants import check_readme_registry_drift

    assert check_readme_registry_drift(violating_repo, ["docs/notes.md"]) == []


def test_building_a_fixture_twice_replaces_the_previous_tree(tmp_path: Path):
    first = build("clean", tmp_path / "twice")
    (first / "stale.txt").write_text("stale\n", encoding="utf-8")
    second = build("clean", tmp_path / "twice")
    assert not (second / "stale.txt").exists()


def test_build_fixture_cli_reports_where_it_built(tmp_path: Path, capsys):
    from build_fixture import main as build_main

    assert build_main(["--kind", "clean", "--out", str(tmp_path / "cli")]) == 0
    assert "fixture ready at" in capsys.readouterr().out
