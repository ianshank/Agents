#!/usr/bin/env python3
"""Tests for the coverage-floor pin gate (``scripts/check_coverage_floors.py``).

The point of this guard is that it *fires* when a threshold is lowered, so most of what
follows are mutation tests: they rewrite a floor downwards in a scratch copy of the real
tree and assert the guard fails. A guard that silently stops detecting a weakened
threshold is worse than no guard, because the green tick is read as evidence.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import check_coverage_floors as cf
import pytest
from eval_protected_paths import is_protected

REPO_ROOT = Path(__file__).resolve().parent.parent
# Annotated because `scripts/` is not on mypy_path: the module resolves to Any, and an
# unannotated alias would make every `tmp_path / MANIFEST` an Any under warn_return_any.
MANIFEST: Path = cf.MANIFEST_PATH


# ---------------------------------------------------------------------------
# The live repository
# ---------------------------------------------------------------------------


def test_manifest_loads_from_the_real_repo() -> None:
    units = cf.load_manifest(REPO_ROOT / MANIFEST)
    assert units, "the shipped manifest declares no units"
    assert all(unit.sources for unit in units)


def test_real_repo_passes() -> None:
    units = cf.load_manifest(REPO_ROOT / MANIFEST)
    assert cf.check(REPO_ROOT, units) == []


def test_cli_exits_zero_on_the_real_repo(capsys: pytest.CaptureFixture[str]) -> None:
    assert cf.main(["--repo", str(REPO_ROOT)]) == 0
    assert "OK" in capsys.readouterr().out


def test_every_pinned_source_is_a_protected_path() -> None:
    """A pin is only as strong as the review gate on the file it pins.

    An unprotected threshold file can be lowered with no label and no code owner, which is
    the exact hole this whole change closes — so the manifest's own source list is checked
    against ``PROTECTED_PATTERNS`` rather than trusted.
    """
    units = cf.load_manifest(REPO_ROOT / MANIFEST)
    unprotected = sorted({source.path for unit in units for source in unit.sources if not is_protected(source.path)})
    assert not unprotected, f"pinned but unprotected: {unprotected}"


def test_the_manifest_itself_is_a_protected_path() -> None:
    assert is_protected(MANIFEST.as_posix())


def test_the_guard_hard_codes_no_floor() -> None:
    """Every number the guard compares must come from the manifest or the file it names.

    Checked against the parsed module rather than its text: the docstrings deliberately
    quote ``fail_under = 96`` while explaining the hole this closes, and prose is not a
    threshold. Only real integer literals in the code count.
    """
    tree = ast.parse((REPO_ROOT / "scripts" / "check_coverage_floors.py").read_text(encoding="utf-8"))
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, int)}
    pinned = {unit.pinned_minimum for unit in cf.load_manifest(REPO_ROOT / MANIFEST)}
    assert not (literals & pinned), f"guard hard-codes pinned floor(s): {sorted(literals & pinned)}"


# ---------------------------------------------------------------------------
# Floor extraction, per source kind
# ---------------------------------------------------------------------------


def test_floor_from_pyproject_reads_the_coverage_report_section() -> None:
    text = "[tool.coverage.run]\nfail_under = 1\n\n[tool.coverage.report]\nfail_under = 96\n"
    assert cf.floor_from_pyproject(text) == 96


def test_floor_from_pyproject_returns_none_without_the_section() -> None:
    assert cf.floor_from_pyproject("[project]\nname = 'x'\n") is None


def test_floor_from_gate_script_reads_the_literal() -> None:
    assert cf.floor_from_gate_script("pytest --cov-branch --cov-fail-under=95\n") == 95


def test_floor_from_gate_script_takes_the_lowest_of_several_stages() -> None:
    """A lowered later stage must not hide behind an untouched earlier one."""
    text = "pytest --cov-fail-under=96\npytest --cov-fail-under=40\n"
    assert cf.floor_from_gate_script(text) == 40


def test_floor_from_gate_script_returns_none_when_absent() -> None:
    assert cf.floor_from_gate_script("pytest -q\n") is None


def test_floor_from_coveragerc_reads_the_report_section() -> None:
    assert cf.floor_from_coveragerc("[run]\nbranch = True\n\n[report]\nfail_under = 85\n") == 85


def test_floor_from_coveragerc_returns_none_on_a_non_numeric_value() -> None:
    assert cf.floor_from_coveragerc("[report]\nfail_under = high\n") is None


def test_floor_from_coveragerc_returns_none_on_malformed_ini() -> None:
    assert cf.floor_from_coveragerc("not an ini at all\n") is None


# ---------------------------------------------------------------------------
# Mutation tests: the guard must FAIL when a floor is lowered
# ---------------------------------------------------------------------------


def _scratch_repo(tmp_path: Path) -> Path:
    """A copy of just the files the manifest names, plus the manifest itself."""
    root = tmp_path / "repo"
    manifest_src = REPO_ROOT / MANIFEST
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_src, root / MANIFEST)
    for unit in cf.load_manifest(manifest_src):
        for source in unit.sources:
            target = root / source.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / source.path, target)
    return root


def _lower_floor(root: Path, rel: str, new_value: int) -> tuple[int, int]:
    """Rewrite the floor declared in *rel* to *new_value*; return (old, new)."""
    path = root / rel
    text = path.read_text(encoding="utf-8")
    unit, source = next((u, s) for u in cf.load_manifest(root / MANIFEST) for s in u.sources if s.path == rel)
    old = cf.EXTRACTORS[source.kind](text)
    assert old is not None, f"no floor found in {rel}"
    path.write_text(text.replace(str(old), str(new_value), 1), encoding="utf-8")
    assert cf.EXTRACTORS[source.kind](path.read_text(encoding="utf-8")) == new_value
    return unit.pinned_minimum, new_value


@pytest.mark.parametrize(
    "rel",
    [
        "pyproject.toml",
        "scripts/quality-gate.sh",
        "scripts/.coveragerc",
        "agent-core/pyproject.toml",
        "claude-foundation/scripts/quality-gate.sh",
    ],
)
def test_lowering_any_declared_floor_fails(tmp_path: Path, rel: str) -> None:
    """The assertion that proves the guard works: 96 -> 50 used to pass every gate."""
    root = _scratch_repo(tmp_path)
    pinned, lowered = _lower_floor(root, rel, 50)
    findings = cf.check(root, cf.load_manifest(root / MANIFEST))
    assert [f.path for f in findings] == [rel]
    assert findings[0].kind == "floor_lowered"
    assert (findings[0].pinned, findings[0].declared) == (pinned, lowered)


def test_raising_a_declared_floor_is_allowed(tmp_path: Path) -> None:
    root = _scratch_repo(tmp_path)
    path = root / "agent-core" / "pyproject.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("fail_under = 95", "fail_under = 99"), encoding="utf-8")
    assert cf.check(root, cf.load_manifest(root / MANIFEST)) == []


def test_cli_exits_one_and_names_file_pin_and_actual(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _scratch_repo(tmp_path)
    pinned, lowered = _lower_floor(root, "pyproject.toml", 50)
    assert cf.main(["--repo", str(root)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "pyproject.toml" in out
    assert f"pinned minimum {pinned}" in out
    assert f"actual {lowered}" in out


def test_json_report_is_machine_readable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _scratch_repo(tmp_path)
    _lower_floor(root, "pyproject.toml", 50)
    assert cf.main(["--repo", str(root), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is False
    assert [f["path"] for f in payload["findings"]] == ["pyproject.toml"]


def test_verbose_logging_reports_each_source(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    root = _scratch_repo(tmp_path)
    with caplog.at_level("DEBUG", logger=cf.logger.name):
        assert cf.main(["--repo", str(root), "--verbose"]) == 0
    assert any("declares" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Missing sources
# ---------------------------------------------------------------------------


def test_a_deleted_source_file_is_a_finding(tmp_path: Path) -> None:
    """Deleting the file is as effective as lowering the number, so it must not pass."""
    root = _scratch_repo(tmp_path)
    (root / "scripts" / ".coveragerc").unlink()
    findings = cf.check(root, cf.load_manifest(root / MANIFEST))
    assert [(f.kind, f.path) for f in findings] == [("source_missing", "scripts/.coveragerc")]
    assert findings[0].declared is None


def test_a_source_that_no_longer_declares_a_floor_is_a_finding(tmp_path: Path) -> None:
    root = _scratch_repo(tmp_path)
    path = root / "scripts" / "quality-gate.sh"
    path.write_text(path.read_text(encoding="utf-8").replace("--cov-fail-under=96", ""), encoding="utf-8")
    findings = cf.check(root, cf.load_manifest(root / MANIFEST))
    assert [(f.kind, f.path) for f in findings] == [("floor_unreadable", "scripts/quality-gate.sh")]


def test_missing_manifest_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cf.main(["--repo", str(tmp_path)]) == cf.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err


def test_load_manifest_raises_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(cf.ManifestError, match="not found"):
        cf.load_manifest(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# Malformed manifests: fail closed, never a partial (and therefore green) check
# ---------------------------------------------------------------------------


def _manifest(tmp_path: Path, text: str) -> Path:
    path = tmp_path / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("units: [\n", "not readable YAML"),
        ("- just\n- a\n- list\n", "must be a mapping"),
        ("version: 1\n", "'units' must be a non-empty list"),
        ("units: []\n", "'units' must be a non-empty list"),
        ("units:\n  - notamapping\n", "must be a mapping"),
        ("units:\n  - pinned_minimum: 96\n    sources: [{kind: pyproject, path: a}]\n", "'name'"),
        ("units:\n  - name: root\n    sources: [{kind: pyproject, path: a}]\n", "pinned_minimum"),
        (
            "units:\n  - name: root\n    pinned_minimum: true\n    sources: [{kind: pyproject, path: a}]\n",
            "pinned_minimum",
        ),
        (
            "units:\n  - name: root\n    pinned_minimum: 101\n    sources: [{kind: pyproject, path: a}]\n",
            "pinned_minimum",
        ),
        ("units:\n  - name: root\n    pinned_minimum: 96\n", "'sources' must be a non-empty list"),
        ("units:\n  - name: root\n    pinned_minimum: 96\n    sources: []\n", "'sources' must be a non-empty list"),
        ("units:\n  - name: root\n    pinned_minimum: 96\n    sources: [7]\n", "must be a mapping"),
        (
            "units:\n  - name: root\n    pinned_minimum: 96\n    sources: [{kind: nope, path: a}]\n",
            "source kind",
        ),
        (
            "units:\n  - name: root\n    pinned_minimum: 96\n    sources: [{kind: pyproject, path: '  '}]\n",
            "'path' must be a non-empty string",
        ),
        (
            "units:\n"
            "  - name: root\n    pinned_minimum: 96\n    sources: [{kind: pyproject, path: a}]\n"
            "  - name: root\n    pinned_minimum: 96\n    sources: [{kind: pyproject, path: b}]\n",
            "duplicate unit name",
        ),
    ],
)
def test_malformed_manifest_raises(tmp_path: Path, text: str, match: str) -> None:
    with pytest.raises(cf.ManifestError, match=match):
        cf.load_manifest(_manifest(tmp_path, text))


def test_malformed_manifest_exits_two_rather_than_passing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A manifest the guard cannot fully understand must never report a pass."""
    _manifest(tmp_path, "units:\n  - name: root\n    pinned_minimum: 96\n")
    assert cf.main(["--repo", str(tmp_path)]) == cf.EXIT_USAGE_ERROR
    assert "usage error" in capsys.readouterr().err


def test_an_unreadable_source_file_is_a_finding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An I/O error on a pinned file is reported, not raised through the CLI."""
    root = _scratch_repo(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _boom)
    unit = cf.Unit(name="u", pinned_minimum=96, sources=(cf.Source(kind="pyproject", path="pyproject.toml"),))
    findings = cf.check(root, [unit])
    assert [(f.kind, f.detail.startswith("cannot read")) for f in findings] == [("floor_unreadable", True)]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_render_text_ok_line_counts_units_and_sources() -> None:
    units = cf.load_manifest(REPO_ROOT / MANIFEST)
    text = cf.render_text([], units, MANIFEST)
    assert "OK" in text
    assert str(sum(len(u.sources) for u in units)) in text


def test_render_text_explains_that_lowering_needs_review() -> None:
    unit = cf.Unit(name="u", pinned_minimum=96, sources=(cf.Source(kind="pyproject", path="pyproject.toml"),))
    finding = cf.Finding(
        kind="floor_lowered",
        unit="u",
        path="pyproject.toml",
        source_kind="pyproject",
        pinned=96,
        declared=50,
        detail="declared coverage floor is below the pinned minimum",
    )
    text = cf.render_text([finding], [unit], MANIFEST)
    assert "eval-change-approved" in text
    assert "pinned minimum 96, actual 50" in text


def test_manifest_override_flag_is_honoured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "elsewhere.yaml"
    path.write_text(
        "units:\n  - name: root\n    pinned_minimum: 1\n    sources: [{kind: pyproject, path: pyproject.toml}]\n",
        encoding="utf-8",
    )
    assert cf.main(["--repo", str(REPO_ROOT), "--manifest", str(path)]) == 0
    assert "elsewhere.yaml" in capsys.readouterr().out
