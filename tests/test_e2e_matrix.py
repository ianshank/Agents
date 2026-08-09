"""Tests and CLI for the generated end-to-end test matrix.

Run as a script to (re)generate or verify the committed artifact:

    python tests/test_e2e_matrix.py --update      # regenerate from artifacts/e2e-report/
    python tests/test_e2e_matrix.py --check       # exit 1 if the committed artifact is stale

Exit codes:
    0 - artifact written, or the committed artifact is fresh
    1 - the artifact is stale, or a policy problem refused the render
    2 - configuration / usage error (no run report, unreadable runner)
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

# Script-mode bootstrap: `python tests/test_e2e_matrix.py --update` starts with tests/ as
# sys.path[0] and no conftest handling, so the repo root (and src/, for an uninstalled
# checkout) must be prepended before the `tests.` imports resolve.
if __package__ in (None, ""):
    for _p in (str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent.parent / "src")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

from tests import _e2e_matrix as em

ROOT = Path(__file__).resolve().parent.parent

#: A provenance stamp fixed for tests, so rendering stays a pure function of the inputs.
FIXED_STAMP = "2026-01-02T03:04:05+00:00"

FIXED_PROVENANCE = em.Provenance(
    sha="0" * 40,
    branch="test",
    generated_at=FIXED_STAMP,
    host="test-host",
    python_version="3.11.0",
    runner_invocation="scripts/run_all_e2e.ps1 -Tiers all",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_report(report_dir: Path, records: list[dict[str, object]], *, bom: bool = False) -> Path:
    """Materialise a synthetic ``summary.json`` the way the PowerShell runner would."""
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records if len(records) != 1 else records[0], indent=2)
    encoding = "utf-8-sig" if bom else "utf-8"
    path = report_dir / "summary.json"
    path.write_text(payload, encoding=encoding, newline="\n")
    return path


def _record(name: str, tier: str = "C", status: str = "PASS", detail: str = "ok") -> dict[str, object]:
    return {"tier": tier, "name": name, "status": status, "detail": detail, "duration_ms": 12}


@pytest.fixture
def runner_text() -> str:
    """The real runner. Parsing it is the point: a synthetic stand-in would prove nothing."""
    return em.RUNNER_PATH.read_text(encoding="utf-8")


@pytest.fixture
def declared(runner_text: str) -> tuple[em.DeclaredStep, ...]:
    return em.parse_declared_steps(runner_text)


# ---------------------------------------------------------------------------
# Cross-language drift guards: the runner is the only source of the step list
# ---------------------------------------------------------------------------


class TestRunnerInventory:
    """The declared inventory must track ``run_all_e2e.ps1`` without restating it.

    These are the guards that make the artifact self-maintaining: a step added to the
    runner shows up here with no edit to the engine, and a grammar change that breaks the
    parser fails loudly instead of silently shrinking the matrix.
    """

    def test_every_tier_the_runner_uses_is_represented(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        tiers = {step.tier for step in declared}
        assert {"PRE", "A", "B", "C", "D"} <= tiers, f"parser lost a tier; found {sorted(tiers)}"

    def test_loop_declared_suites_are_resolved_not_dropped(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        """`Invoke-PytestStep 'A' $s.name` must resolve through `$suites`, not vanish."""
        names = {step.name for step in declared}
        assert "suite:root" in names
        assert "suite:agent-core" in names, "the $suites array was not resolved"

    def test_loop_declared_judges_are_resolved(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        """`Invoke-CmdStep 'D' $j.name` must resolve through `$liveJudges`."""
        assert "live:judge-openai" in {step.name for step in declared}

    def test_steps_declared_inside_catch_and_else_branches_are_found(
        self, declared: tuple[em.DeclaredStep, ...]
    ) -> None:
        """Several `Add-Result` calls sit inline after `catch {` / `else {` on one line.

        A line-anchored regex silently drops exactly those, which are the failure-path
        steps most worth reporting.
        """
        assert "live:langfuse-smoke" in {step.name for step in declared}

    def test_commands_are_recovered_across_backtick_continuations(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        by_name = {step.name: step for step in declared}
        assert by_name["cli:eval-harness list-plugins"].command.startswith("python -m eval_harness.cli")

    def test_a_grammar_change_fails_loudly(self) -> None:
        with pytest.raises(em.MatrixError, match="call-site grammar"):
            em.parse_declared_steps("# a runner with no step calls at all\n")

    def test_each_live_judge_config_key_matches_its_constructor(self) -> None:
        """The runner writes `judge.params.<param>`; the judge class must accept it.

        The three judges disagree: OpenAI and Anthropic take `model`, Bedrock takes
        `model_id`. Emitting `model` for all three made live:judge-bedrock raise
        `TypeError: unexpected keyword argument 'model'` the first time it actually ran -
        which took until an environment happened to supply AWS credentials, because the
        step had only ever SKIPped. Signature drift must fail here, not in Tier D.
        """
        import inspect

        from eval_harness.judges import JUDGES

        specs = em.runner_judge_specs()
        assert specs, "no $liveJudges entries parsed from the runner"
        for step_name, spec in sorted(specs.items()):
            judge_cls = JUDGES.get(spec["type"])
            accepted = set(inspect.signature(judge_cls.__init__).parameters)
            assert spec["param"] in accepted, (
                f"{step_name}: runner writes params.{spec['param']}, but "
                f"{judge_cls.__name__}.__init__ accepts {sorted(accepted - {'self'})}"
            )

    def test_runner_env_gates_match_the_smokes(self, runner_text: str) -> None:
        """The runner restates each live step's variables inline; the smokes own them.

        Nothing tied the two together before this test, unlike the skip code, which is
        guarded. A rename on either side used to slip through as a step that silently
        skipped forever.
        """
        asserted = {frozenset(names) for names in em.runner_env_assertions(runner_text)}
        derived = {frozenset(names) for names in em.smoke_credentials(ROOT).values() if names}
        missing = derived - asserted
        assert not missing, f"the runner gates on no such variable set: {sorted(map(sorted, missing))}"


# ---------------------------------------------------------------------------
# Derivation: every fact comes from the file that owns it
# ---------------------------------------------------------------------------


class TestDerivation:
    """Facts are read from their owning file, and cross-checked against a second anchor."""

    def test_members_agree_with_the_makefile(self) -> None:
        """Two independent anchors for the member list must not drift apart."""
        assert em.derive_members(ROOT) == em.makefile_check_members(ROOT)

    def test_every_member_declares_a_coverage_floor(self) -> None:
        packages = em.derive_packages(ROOT, em.derive_workflows(ROOT))
        floorless = [pkg.name for pkg in packages if pkg.floor is None]
        assert not floorless, f"no coverage floor derived for {floorless}"

    def test_floor_anchors_agree_with_each_other(self) -> None:
        """A pyproject floor and its generated quality-gate script must state one number."""
        for pkg in em.derive_packages(ROOT, em.derive_workflows(ROOT)):
            values = {anchor.split("=")[-1] for anchor in pkg.anchors}
            assert len(values) <= 1, f"{pkg.name} declares disagreeing floors: {sorted(pkg.anchors)}"

    def test_scripts_floor_comes_from_the_coveragerc(self) -> None:
        packages = {pkg.name: pkg for pkg in em.derive_packages(ROOT, em.derive_workflows(ROOT))}
        assert packages["scripts"].floor is not None
        assert "coveragerc" in packages["scripts"].anchors[0]

    def test_workflows_map_to_real_files(self) -> None:
        for names in em.derive_workflows(ROOT).values():
            for name in names:
                assert (ROOT / ".github" / "workflows" / name).is_file()

    def test_credentials_normalise_both_smoke_shapes(self) -> None:
        """One smoke exposes a tuple, the other a bare string; both must yield a tuple."""
        creds = em.derive_live_credentials(ROOT)
        assert creds["live:langfuse-smoke"], "REQUIRED_ENV tuple was not read"
        assert creds["live:phoenix-smoke"], "ENV_ENDPOINT string was not normalised"
        for names in creds.values():
            assert all(isinstance(name, str) for name in names)


# ---------------------------------------------------------------------------
# Census parsing
# ---------------------------------------------------------------------------


class TestCensusParsing:
    """The report is written by PowerShell, so its quirks are the parser's problem."""

    def test_reads_a_bom_prefixed_report(self, tmp_path: Path) -> None:
        """`Set-Content -Encoding UTF8` emits a BOM; plain utf-8 json.load rejects it."""
        _write_report(tmp_path, [_record("a"), _record("b")], bom=True)
        assert len(em.load_run_steps(tmp_path)) == 2

    def test_reads_a_single_result_rendered_as_an_object(self, tmp_path: Path) -> None:
        """ConvertTo-Json emits an object, not an array, for exactly one result.

        A failed pre-flight aborts the run after one record, so this shape is the report
        of the very failure most worth rendering.
        """
        _write_report(tmp_path, [_record("preflight-imports", tier="PRE", status="FAIL")])
        steps = em.load_run_steps(tmp_path)
        assert [s.name for s in steps] == ["preflight-imports"]

    def test_a_missing_report_is_a_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(em.MatrixError, match="no run report"):
            em.load_run_steps(tmp_path)

    def test_malformed_json_names_the_file(self, tmp_path: Path) -> None:
        (tmp_path / "summary.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(em.MatrixError, match="cannot read"):
            em.load_run_steps(tmp_path)

    def test_a_malformed_duration_does_not_sink_the_report(self, tmp_path: Path) -> None:
        _write_report(tmp_path, [_record("a") | {"duration_ms": "not-a-number"}, _record("b")])
        assert em.load_run_steps(tmp_path)[0].duration_ms == 0

    def test_junit_counters_are_summed_across_testsuite_elements(self, tmp_path: Path) -> None:
        (tmp_path / "root.xml").write_text(
            '<testsuites><testsuite tests="10" failures="1" errors="0" skipped="2"/>'
            '<testsuite tests="5" failures="0" errors="1" skipped="0"/></testsuites>',
            encoding="utf-8",
        )
        artifact = em.load_junit(tmp_path)["root"]
        assert (artifact.tests, artifact.failures, artifact.errors, artifact.skipped) == (15, 1, 1, 2)

    def test_a_corrupt_junit_file_warns_and_is_skipped(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        (tmp_path / "broken.xml").write_text("<testsuite", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            assert em.load_junit(tmp_path) == {}
        assert any("unreadable JUnit" in r.getMessage() for r in caplog.records)

    def test_evidence_is_empty_when_the_runner_wrote_no_log(self, tmp_path: Path) -> None:
        assert em.evidence_for("cli:nothing", tmp_path) == ""

    def test_safe_step_name_matches_the_runners_scriptblock(self) -> None:
        """The runner derives log filenames with `-replace '[^\\w.-]', '_'`."""
        assert em.safe_step_name("cli:eval-harness run --set") == "cli_eval-harness_run_--set"


# ---------------------------------------------------------------------------
# Policy: no vacuous artifact
# ---------------------------------------------------------------------------


class TestPolicy:
    """The guards that stop a matrix from reporting a clean sheet for nothing."""

    def test_an_empty_census_is_refused(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        problems = em.policy_problems([], declared)
        assert any("vacuous" in p for p in problems)

    def test_an_undeclared_step_is_a_hard_problem(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        """A step the runner grew that the parser cannot see must fail, not be dropped."""
        problems = em.policy_problems([em.RunStep("C", "cli:brand-new", "PASS", "", 1)], declared)
        assert any("not declared" in p for p in problems)

    def test_a_clean_run_has_no_problems(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        run = [em.RunStep(step.tier, step.name, "PASS", "ok", 1) for step in declared]
        assert em.policy_problems(run, declared) == []

    def test_build_sheets_refuses_a_report_with_an_unknown_step(self, tmp_path: Path) -> None:
        _write_report(tmp_path, [_record("cli:brand-new"), _record("suite:root", tier="A")])
        with pytest.raises(em.MatrixError, match="not declared"):
            em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)


# ---------------------------------------------------------------------------
# Rendering and determinism
# ---------------------------------------------------------------------------


class TestRendering:
    """Byte-stability is the property that lets the artifact be committed and gated."""

    def test_csv_uses_lf_regardless_of_platform(self) -> None:
        """The runner runs on Windows while CI runs on Linux; the artifact must not differ."""
        sheet = em.Sheet(name="S", columns=("A", "B"), rows=(("1", "2"),))
        assert "\r" not in em.render_csv(sheet)

    def test_newlines_in_a_cell_cannot_split_a_row(self) -> None:
        sheet = em.Sheet(name="S", columns=("A",), rows=(("line one\nline two",),))
        assert em.render_csv(sheet).splitlines() == ["A", "line one line two"]

    def test_a_pipe_in_a_cell_cannot_fabricate_a_markdown_column(self) -> None:
        sheet = em.Sheet(name="S", columns=("A",), rows=(("a|b",),))
        assert "a\\|b" in em.render_markdown([sheet])

    def test_a_conflict_marker_cell_is_defused(self) -> None:
        """The repo-wide guard reads every decodable tracked file and would reject this."""
        sheet = em.Sheet(name="S", columns=("A",), rows=(("=======",),))
        assert "\n=======" not in em.render_csv(sheet)

    def test_rendering_is_a_pure_function_of_its_inputs(self, tmp_path: Path) -> None:
        _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
        first = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
        second = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
        assert em.render_markdown(first) == em.render_markdown(second)
        assert [em.render_csv(s) for s in first] == [em.render_csv(s) for s in second]

    def test_every_declared_step_gets_a_row_even_when_not_reached(self, tmp_path: Path) -> None:
        """A tier that never ran must be visible as NOT-RUN, not absent."""
        _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
        matrix = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)[0]
        statuses = {row[matrix.columns.index("Status")] for row in matrix.rows}
        assert em.NOT_RUN in statuses
        assert len(matrix.rows) == len(em.parse_declared_steps(em.RUNNER_PATH.read_text(encoding="utf-8")))

    def test_csv_filenames_are_stable_and_safe(self) -> None:
        assert em.csv_filename(em.Sheet(name="Test Matrix", columns=())) == "test_matrix.csv"


class TestRedaction:
    """Run output is attacker-adjacent text, and this artifact is committed."""

    def test_a_credential_bearing_detail_never_reaches_a_cell(self, tmp_path: Path) -> None:
        secret = "s3cr3t-key-value"  # a synthetic value, not a credential
        _write_report(
            tmp_path,
            [
                _record("suite:root", tier="A", detail=f"failed against https://user:{secret}@host?api_key={secret}"),
                _record("cli:bregress"),
            ],
        )
        sheets = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE, scrub=lambda t: t.replace(secret, "***"))
        rendered = em.render_markdown(sheets) + "".join(em.render_csv(s) for s in sheets)
        assert secret not in rendered


# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------


class TestWorkbook:
    """The xlsx is an optional, reproducible export of the same sheet model."""

    def test_absent_openpyxl_explains_itself(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`sys.modules[...] = None` forces ImportError even where openpyxl is installed.

        The repo's documented idiom for covering an SDK-absent path in a venv that has
        every extra.
        """
        from tests import _e2e_matrix_xlsx as xw

        monkeypatch.setitem(sys.modules, "openpyxl", None)
        with pytest.raises(ImportError, match="openpyxl is required"):
            xw.write_workbook([], tmp_path / "x.xlsx", stamp_iso=FIXED_STAMP)

    def test_csv_and_markdown_do_not_need_openpyxl(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The engine must stay importable and useful with no spreadsheet library."""
        monkeypatch.setitem(sys.modules, "openpyxl", None)
        sheet = em.Sheet(name="S", columns=("A",), rows=(("1",),))
        assert em.write_artifacts([sheet], tmp_path)

    def test_workbook_is_byte_reproducible(self, tmp_path: Path) -> None:
        """openpyxl stamps `now()` into core.xml and zipfile stamps entry mtimes.

        Both are pinned from the run's provenance, so an unchanged run regenerates an
        identical file instead of churning the committed artifact on every invocation.
        """
        pytest.importorskip("openpyxl")
        from tests import _e2e_matrix_xlsx as xw

        sheets = [em.Sheet(name="Test Matrix", columns=("Step", "Status"), rows=(("a", "PASS"), ("b", "FAIL")))]
        first = xw.write_workbook(sheets, tmp_path / "a.xlsx", stamp_iso=FIXED_STAMP)
        second = xw.write_workbook(sheets, tmp_path / "b.xlsx", stamp_iso=FIXED_STAMP)
        assert first.read_bytes() == second.read_bytes()

    def test_workbook_entries_carry_the_pinned_timestamp(self, tmp_path: Path) -> None:
        pytest.importorskip("openpyxl")
        from tests import _e2e_matrix_xlsx as xw

        path = xw.write_workbook(
            [em.Sheet(name="S", columns=("A",), rows=(("1",),))], tmp_path / "a.xlsx", stamp_iso=FIXED_STAMP
        )
        with zipfile.ZipFile(path) as archive:
            stamps = {info.date_time for info in archive.infolist()}
        assert stamps == {xw.parse_stamp(FIXED_STAMP)}

    def test_workbook_round_trips_the_sheet_model(self, tmp_path: Path) -> None:
        pytest.importorskip("openpyxl")
        import openpyxl

        from tests import _e2e_matrix_xlsx as xw

        sheets = [em.Sheet(name="Test Matrix", columns=("Step", "Status"), rows=(("a", "PASS"),))]
        path = xw.write_workbook(sheets, tmp_path / "a.xlsx", stamp_iso=FIXED_STAMP)
        loaded = openpyxl.load_workbook(path)
        assert loaded.sheetnames == ["Test Matrix"]
        assert [cell.value for cell in loaded["Test Matrix"][1]] == ["Step", "Status"]

    def test_an_unparseable_stamp_falls_back_to_the_zip_epoch(self, caplog: pytest.LogCaptureFixture) -> None:
        from tests import _e2e_matrix_xlsx as xw

        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix_xlsx"):
            assert xw.parse_stamp("not-a-timestamp") == xw.ZIP_EPOCH
        assert any("unparseable provenance timestamp" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Logging (house convention: name the logger, assert the negative too)
# ---------------------------------------------------------------------------


def test_census_logs_diagnostics(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    with caplog.at_level(logging.DEBUG, logger="tests._e2e_matrix"):
        em.load_run_steps(tmp_path)
    assert any("census:" in r.getMessage() for r in caplog.records)


def test_nothing_is_logged_at_the_default_level(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Diagnostics stay diagnostics: a clean render must be silent at WARNING and above."""
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
        em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
    assert [r for r in caplog.records if r.name == "tests._e2e_matrix"] == []


# ---------------------------------------------------------------------------
# Freshness of the committed artifact
# ---------------------------------------------------------------------------


def test_freshness_reports_a_missing_document_as_stale(tmp_path: Path) -> None:
    fresh, rendered = em.artifact_is_fresh([em.Sheet(name="S", columns=("A",))], tmp_path)
    assert not fresh
    assert "does not exist" in em.freshness_failure_message(rendered, tmp_path)


def test_freshness_diff_is_bounded(tmp_path: Path) -> None:
    """A stale artifact must say *why*, without pasting an unbounded diff into CI output."""
    sheet = em.Sheet(name="S", columns=("A",), rows=tuple((str(n),) for n in range(200)))
    em.write_artifacts([em.Sheet(name="S", columns=("A",))], tmp_path)
    _, rendered = em.artifact_is_fresh([sheet], tmp_path)
    message = em.freshness_failure_message(rendered, tmp_path)
    assert "truncated" in message
    assert len(message.splitlines()) <= em.MAX_DIFF_LINES + 2


@pytest.mark.skipif(
    not (em.DEFAULT_REPORT_DIR / "summary.json").is_file(),
    reason="no e2e run report present; the artifact can only be verified after a run",
)
def test_matrix_artifact_is_fresh() -> None:
    """The committed artifact matches what the current run report renders.

    Skipped when `artifacts/e2e-report/` is absent, which is the normal state in CI: the
    e2e runner is a local/Windows operation and CI never produces a report to compare
    against. The guard is meaningful exactly where a report exists.
    """
    sheets = em.build_sheets(provenance=_provenance())
    fresh, rendered = em.artifact_is_fresh(sheets, em.DEFAULT_OUT_DIR)
    assert fresh, em.freshness_failure_message(rendered, em.DEFAULT_OUT_DIR)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    """A git value for provenance, or an empty string outside a checkout."""
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _provenance(sha: str | None = None, stamp: str | None = None) -> em.Provenance:
    """Run identity. Volatile values are overridable so a render can be reproduced."""
    return em.Provenance(
        sha=sha or _git("rev-parse", "HEAD"),
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        generated_at=stamp or _git("log", "-1", "--format=%cI"),
        host=platform.platform(),
        python_version=platform.python_version(),
        runner_invocation="pwsh -NoProfile -File scripts/run_all_e2e.ps1 -Tiers all -HypothesisProfile ci",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--update", action="store_true", help="(Re)write the committed matrix artifact")
    group.add_argument("--check", action="store_true", help="Exit 1 if the committed artifact is stale")
    parser.add_argument("--report", type=Path, default=em.DEFAULT_REPORT_DIR, help="Run report directory")
    parser.add_argument("--out", type=Path, default=em.DEFAULT_OUT_DIR, help="Artifact output directory")
    parser.add_argument("--sha", default=None, help="Override the provenance commit (for reproducible renders)")
    parser.add_argument("--timestamp", default=None, help="Override the provenance timestamp")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Generate or verify the committed matrix. See the module docstring for exit codes."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)-8s %(name)s: %(message)s"
    )

    scrub = _load_scrubber()
    try:
        sheets = em.build_sheets(
            args.report,
            provenance=_provenance(args.sha, args.timestamp),
            env_present=sorted(_present_credentials()),
            scrub=scrub,
        )
    except em.MatrixError as exc:
        logging.getLogger(__name__).error("%s", exc)
        print(f"e2e-matrix: {exc}", file=sys.stderr)
        return 2 if "no run report" in str(exc) or "runner not found" in str(exc) else 1

    if args.check:
        fresh, rendered = em.artifact_is_fresh(sheets, args.out)
        if not fresh:
            print(em.freshness_failure_message(rendered, args.out), file=sys.stderr)
            return 1
        print(f"{(args.out / 'e2e-matrix.md').as_posix()} is fresh")
        return 0

    written = em.write_artifacts(sheets, args.out)
    stamp = next(row[1] for row in sheets[-1].rows if row[0] == "Generated at (UTC)")
    try:
        from tests import _e2e_matrix_xlsx as xw

        written.append(xw.write_workbook(sheets, args.out / "e2e-test-matrix.xlsx", stamp_iso=stamp))
    except ImportError as exc:
        logging.getLogger(__name__).warning("workbook not written: %s", exc)
    for path in written:
        print(path.relative_to(ROOT).as_posix())
    return 0


def _present_credentials() -> set[str]:
    """Which live-step variables this environment actually supplies. Names only."""
    import os

    required: set[str] = set()
    for names in em.derive_live_credentials(ROOT).values():
        required.update(names)
    return {name for name in required if os.environ.get(name)}


def _load_scrubber() -> Callable[[str], str] | None:
    """Reuse the smokes' redaction so committed cells cannot carry a credential."""
    smokes = ROOT / "scripts" / "smokes"
    if str(smokes) not in sys.path:
        sys.path.append(str(smokes))
    try:
        import _smoke_lib
    except ImportError:  # pragma: no cover - the smokes ship with the repo
        return None
    secrets = [value for name, value in __import__("os").environ.items() if _is_secret_name(name) and value]
    return lambda text: _smoke_lib.redact(text, secrets)


def _is_secret_name(name: str) -> bool:
    """Environment variables whose *values* must never appear in a committed cell."""
    return name.endswith(("_KEY", "_SECRET", "_TOKEN", "_PASSWORD")) or name.endswith("_BASE_URL")


if __name__ == "__main__":
    sys.exit(main())
