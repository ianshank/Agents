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
import datetime as dt
import json
import logging
import os
import platform
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
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

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

#: A provenance stamp fixed for tests, so rendering stays a pure function of the inputs.
FIXED_STAMP = "2026-01-02T03:04:05+00:00"

#: Exit codes, per the module docstring's contract.
EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_USAGE_ERROR = 2


@dataclass(frozen=True)
class SubprocessConfig:
    """Timeouts for this module's own subprocess calls (AGENTS.md: no hard-coded numeric
    defaults at call sites)."""

    #: `git` should answer near-instantly; generous only to tolerate a slow CI runner.
    git_timeout_seconds: int = 30
    #: The shim-silence probe (`test_sitecustomize_is_silent_off_windows`) starts a bare
    #: interpreter, which is slower to spin up under load than the `git` calls above.
    shim_probe_timeout_seconds: int = 60


DEFAULT_SUBPROCESS_CONFIG = SubprocessConfig()

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
    path = report_dir / em.SUMMARY_FILENAME
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

    def test_commands_are_recovered_for_every_step_that_has_one(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        """Three declaration shapes each hid a command, and each needed its own fix.

        A multi-line array (PowerShell keeps an expression open inside parens, with no
        backtick), an array passed by variable through a loop, and a step whose first
        textual mention is the SKIP branch that carries no arguments. Together they left
        the Command column empty for 23 of 40 steps - the one datum a reader needs to
        reproduce a step by hand.

        The only steps legitimately without a command are the assertion-only ones, which
        validate a file the previous step wrote rather than running anything.
        """
        by_name = {step.name: step for step in declared}
        assert by_name["cli:eval-harness compare"].command.startswith("python -m eval_harness.cli compare")
        assert by_name["suite:root"].command.startswith("python -m pytest")
        assert by_name["live:judge-openai"].command.startswith("python -m eval_harness.cli run")
        assert by_name["preflight-imports"].command.startswith("python -c import flow_protocol")

        commandless = {name for name, step in by_name.items() if not step.command}
        assert commandless == {"cli:bregress json-valid", "cli:proxy_eval json-valid"}, (
            f"unexpected step(s) without a command: {sorted(commandless)}"
        )

    def test_invoke_cmdstep_does_not_misread_skipcodes_as_a_junit_path(self) -> None:
        """`Invoke-CmdStep`'s third positional is `SkipCodes`, not `Junit`.

        `_call_details` used to apply `Invoke-PytestStep`'s (WorkDir, Junit) signature to
        every verb, safe today only because every real `Invoke-CmdStep` call passes
        `SkipCodes` as an inline `@(...)` array the positional-token regex does not match. A
        bare-variable `SkipCodes` argument -- which resolves to a real string -- must still
        not be read as a JUnit filename.
        """
        source = (
            "$skipCodes = 'notreallyajunitfile.xml'\n"
            "Invoke-CmdStep 'C' 'cli:example' @('-m', 'x') 'experiments/backend-validation' $skipCodes\n"
        )
        declared = em.parse_declared_steps(source)
        step = next(s for s in declared if s.name == "cli:example")
        assert step.workdir == "experiments/backend-validation"
        assert step.junit == ""

    def test_no_declared_step_is_dropped_by_the_parser(self, runner_text: str) -> None:
        """Sweep the runner independently of the call-site grammar and reconcile.

        The other guards here assert that a handful of known names are present, which cannot
        notice a step added through a call shape the parser does not understand. This scans
        for every ``area:rest`` token in the file instead, so a new step declared any way at
        all has to show up in the inventory or fail here.

        The one non-step token of that shape is a pytest plugin spec (``-p no:cacheprovider``),
        excluded by the flag that precedes it rather than by name.
        """
        import re

        plugin_specs = set(re.findall(r"'-p',\s*'([^']+)'", runner_text))
        swept = {tok for tok in re.findall(r"'([a-z][a-z0-9_-]*:[^']*)'", runner_text)} - plugin_specs
        declared_names = {step.name for step in em.parse_declared_steps(runner_text)}
        assert swept - declared_names == set(), (
            f"the runner declares step(s) the parser never produced: {sorted(swept - declared_names)}"
        )
        assert "preflight-imports" in declared_names, "the pre-flight guard step vanished"

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
        gates = em.runner_env_gates(ROOT)
        declared_by_smokes = em.smoke_credentials(ROOT)
        assert declared_by_smokes, "no smoke-backed live step was discovered from the runner's commands"
        for step, required in sorted(declared_by_smokes.items()):
            assert set(required) == set(gates.get(step, ())), (
                f"{step}: the smoke declares {sorted(required)} but the runner gates on {sorted(gates.get(step, ()))}"
            )


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

    def test_every_unit_resolves_to_the_suite_step_that_exercises_it(self, tmp_path: Path) -> None:
        """A unit whose step name only *qualifies* its name must still be matched.

        The tails are not uniform: `scripts` is exercised by `suite:scripts-gate` and
        `experiments/backend-validation` by `e2e:backend-validation`. Matching on the tail
        alone left both reading NOT-RUN on a run that had exercised them - a false negative
        in exactly the column a reader would trust.
        """
        _write_report(
            tmp_path,
            [
                _record("suite:scripts-gate", tier="A"),
                _record("e2e:backend-validation", tier="C"),
                _record("suite:root", tier="A"),
            ],
        )
        grid = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)[2]
        status = {row[0]: row[grid.columns.index("Suite Status")] for row in grid.rows}
        assert status["scripts"] == "PASS"
        assert status["experiments/backend-validation"] == "PASS"
        assert status["root"] == "PASS"

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
        (tmp_path / em.SUMMARY_FILENAME).write_text("{not json", encoding="utf-8")
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

    def test_a_namespaced_testsuite_element_still_parses(self, tmp_path: Path) -> None:
        """`root.iter("testsuite")` misses a namespaced `{uri}testsuite`; local-tag matching must not."""
        (tmp_path / "root.xml").write_text(
            '<ns:testsuites xmlns:ns="urn:example">'
            '<ns:testsuite tests="3" failures="0" errors="0" skipped="0"/></ns:testsuites>',
            encoding="utf-8",
        )
        artifact = em.load_junit(tmp_path)["root"]
        assert artifact.tests == 3

    def test_a_junit_file_with_no_testsuite_element_is_omitted_not_zero(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A well-formed file with zero `<testsuite>` elements must warn and be dropped.

        `SuiteArtifact(0, 0, 0, 0)` is truthy, so recording it for a file that never
        actually reported test counts would render a specific false "0" -- worse than a
        blank cell -- for what may have been a large suite.
        """
        (tmp_path / "empty.xml").write_text("<testsuites></testsuites>", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            assert em.load_junit(tmp_path) == {}
        assert any("no <testsuite> element found" in r.getMessage() for r in caplog.records)

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

    def test_a_step_observed_under_the_wrong_tier_is_a_policy_problem(
        self, declared: tuple[em.DeclaredStep, ...]
    ) -> None:
        """A step recorded under a tier other than the one it is declared under must fail.

        Otherwise the Test Matrix row (declared tier) and the Summary sheet's per-tier
        counts (observed tier) would silently disagree about which tier ran the step.
        """
        step = declared[0]
        wrong_tier = next(t for t in ("PRE", "A", "B", "C", "D") if t != step.tier)
        problems = em.policy_problems([em.RunStep(wrong_tier, step.name, "PASS", "", 1)], declared)
        assert any("declared under tier" in p for p in problems)

    def test_a_duplicate_step_name_in_the_run_report_is_a_policy_problem(
        self, declared: tuple[em.DeclaredStep, ...]
    ) -> None:
        """Two records for the same step silently drop one from a `{name: step}` dict-build.

        The Summary sheet's declared/observed/not-reached counts would stop adding up with
        no warning if this were not caught here.
        """
        step = declared[0]
        run = [em.RunStep(step.tier, step.name, "PASS", "", 1), em.RunStep(step.tier, step.name, "FAIL", "", 2)]
        problems = em.policy_problems(run, declared)
        assert any("appears more than once" in p for p in problems)

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

    def test_every_live_step_variable_counts_as_a_secret(self) -> None:
        """A suffix heuristic alone left the Bedrock key id unredacted.

        `AWS_ACCESS_KEY_ID` ends in `_ID`, so it matched none of the `_KEY`/`_SECRET`/
        `_TOKEN`/`_PASSWORD`/`_BASE_URL` suffixes -- and it is precisely the variable the
        Bedrock step gates on. The policy now also covers every variable the live steps
        declare, so a new live step is protected when it is added rather than when someone
        remembers to extend the suffix list.
        """
        assert _is_secret_name("AWS_ACCESS_KEY_ID"), "the Bedrock key id must be redacted"
        for names in em.derive_live_credentials(ROOT).values():
            for name in names:
                assert _is_secret_name(name), f"{name} gates a live step but its value is not redacted"
        assert not _is_secret_name("PATH"), "the policy must not redact ordinary variables"


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

    def test_document_modified_time_is_pinned_not_wall_clock(self, tmp_path: Path) -> None:
        """openpyxl overwrites `dcterms:modified` at save time, ignoring what we set.

        Comparing two workbooks written back to back does not reliably catch this - both
        land in the same second most of the time, so the byte-equality test above passed
        while the artifact churned whenever a regeneration straddled a second boundary.
        Asserting the pinned value directly is timing-independent.
        """
        pytest.importorskip("openpyxl")
        from tests import _e2e_matrix_xlsx as xw

        path = xw.write_workbook(
            [em.Sheet(name="S", columns=("A",), rows=(("1",),))], tmp_path / "a.xlsx", stamp_iso=FIXED_STAMP
        )
        with zipfile.ZipFile(path) as archive:
            core = archive.read(xw.CORE_PROPERTIES_PART).decode("utf-8")
        expected = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(*xw.parse_stamp(FIXED_STAMP))
        assert f'<dcterms:modified xsi:type="dcterms:W3CDTF">{expected}</dcterms:modified>' in core

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

    def test_an_offset_stamp_is_converted_to_utc(self) -> None:
        """The pinned components are written with a `Z`, so they must actually be UTC.

        The provenance stamp comes from `git log --format=%cI`, which carries the
        committer's offset - it is UTC only where the commit happened to be made. Taking
        the components verbatim would relabel local time as UTC and move the recorded
        instant by the offset.
        """
        from tests import _e2e_matrix_xlsx as xw

        assert xw.parse_stamp("2026-08-09T12:00:00-07:00") == (2026, 8, 9, 19, 0, 0)
        assert xw.parse_stamp("2026-08-09T19:00:00+00:00") == (2026, 8, 9, 19, 0, 0)
        assert xw.parse_stamp("2026-08-09T19:00:00") == (2026, 8, 9, 19, 0, 0), "a naive stamp is treated as UTC"

    def test_a_stamp_outside_the_zip_range_falls_back_to_the_epoch(self, caplog: pytest.LogCaptureFixture) -> None:
        """ZIP packs the year into 7 bits from 1980, so 2108 raises deep inside `zipfile`."""
        from tests import _e2e_matrix_xlsx as xw

        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix_xlsx"):
            assert xw.parse_stamp("2200-01-01T00:00:00+00:00") == xw.ZIP_EPOCH
            assert xw.parse_stamp("1970-01-01T00:00:00+00:00") == xw.ZIP_EPOCH
        assert any("outside the ZIP range" in r.getMessage() for r in caplog.records)

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
    sheets = [em.Sheet(name="S", columns=("A",))]
    fresh, rendered = em.artifact_is_fresh(sheets, tmp_path)
    assert not fresh
    assert "does not exist" in em.freshness_failure_message(rendered, tmp_path, sheets)


def test_provenance_drift_alone_does_not_make_the_artifact_stale(tmp_path: Path) -> None:
    """Committing the artifact moves HEAD, so its recorded SHA is instantly one behind.

    Judging staleness on that would leave the gate permanently red on the very commit that
    carries the artifact - a check that can never pass teaches people to ignore it. Only
    the derived content counts.
    """
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    first = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
    em.write_artifacts(first, tmp_path / "out")

    moved_on = em.Provenance(
        sha="f" * 40,
        branch=FIXED_PROVENANCE.branch,
        generated_at="2027-09-09T09:09:09+00:00",
        host="a-different-host",
        python_version="3.12.1",
        runner_invocation=FIXED_PROVENANCE.runner_invocation,
    )
    fresh, _ = em.artifact_is_fresh(em.build_sheets(tmp_path, provenance=moved_on), tmp_path / "out")
    assert fresh, "only provenance changed; the artifact is not stale"


def test_a_content_change_still_makes_the_artifact_stale(tmp_path: Path) -> None:
    """The provenance exemption must not swallow a real change in the derived content."""
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    em.write_artifacts(em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE), tmp_path / "out")

    _write_report(tmp_path, [_record("suite:root", tier="A", status="FAIL"), _record("cli:bregress")])
    fresh, _ = em.artifact_is_fresh(em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE), tmp_path / "out")
    assert not fresh, "a status flip must be reported as stale"


def test_freshness_diff_is_bounded(tmp_path: Path) -> None:
    """A stale artifact must say *why*, without pasting an unbounded diff into CI output."""
    sheet = em.Sheet(name="S", columns=("A",), rows=tuple((str(n),) for n in range(200)))
    em.write_artifacts([em.Sheet(name="S", columns=("A",))], tmp_path)
    _, rendered = em.artifact_is_fresh([sheet], tmp_path)
    message = em.freshness_failure_message(rendered, tmp_path, [sheet])
    assert "truncated" in message
    assert len(message.splitlines()) <= em.MAX_DIFF_LINES + 2


@pytest.mark.skipif(
    not (em.DEFAULT_REPORT_DIR / em.SUMMARY_FILENAME).is_file(),
    reason="no e2e run report present; the artifact can only be verified after a run",
)
def test_matrix_artifact_is_fresh() -> None:
    """The committed artifact matches what the current run report renders.

    Skipped when `artifacts/e2e-report/` is absent, which is the normal state in CI: the
    e2e runner is a local/Windows operation and CI never produces a report to compare
    against. The guard is meaningful exactly where a report exists.
    """
    sheets, _ = build_committed_sheets()
    fresh, rendered = em.artifact_is_fresh(sheets, em.DEFAULT_OUT_DIR)
    assert fresh, em.freshness_failure_message(rendered, em.DEFAULT_OUT_DIR, sheets)


@pytest.mark.skipif(
    not (em.DEFAULT_REPORT_DIR / em.SUMMARY_FILENAME).is_file(),
    reason="no e2e run report present; the artifact can only be verified after a run",
)
def test_committed_workbook_is_byte_reproducible(tmp_path: Path) -> None:
    """The committed `.xlsx` has zero freshness coverage from `artifact_is_fresh` by design
    (ADR 0033 §4: it cannot be written without the optional extra, so byte-gating it would
    fail for anyone without openpyxl). README.md nonetheless calls it "byte-reproducible" --
    this is the test that makes that a checked claim rather than an assertion nothing enforces.
    """
    xw = pytest.importorskip("tests._e2e_matrix_xlsx")
    committed = em.DEFAULT_OUT_DIR / em.WORKBOOK_FILENAME
    if not committed.is_file():
        pytest.skip("no committed workbook to compare against")

    sheets, provenance = build_committed_sheets()
    regenerated = xw.write_workbook(sheets, tmp_path / em.WORKBOOK_FILENAME, stamp_iso=provenance.generated_at)
    assert regenerated.read_bytes() == committed.read_bytes()


# ---------------------------------------------------------------------------
# Degraded inputs: every derivation must fail soft or fail loudly, never silently
# ---------------------------------------------------------------------------


class TestDegradedInputs:
    """Each derive_* reads a file that can be absent or malformed on a real machine.

    These paths were the bulk of the module's uncovered lines. They are not defensive
    boilerplate: a missing Makefile or an unreadable coveragerc silently blanks a column
    that a reader would otherwise trust, so each one needs to be pinned deliberately.
    """

    def test_a_non_array_report_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / em.SUMMARY_FILENAME).write_text("42", encoding="utf-8")
        with pytest.raises(em.MatrixError, match="neither an object nor an array"):
            em.load_run_steps(tmp_path)

    def test_a_non_object_result_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / em.SUMMARY_FILENAME).write_text('["not-an-object", 1]', encoding="utf-8")
        with pytest.raises(em.MatrixError, match="non-object result"):
            em.load_run_steps(tmp_path)

    def test_a_null_duration_becomes_zero(self, tmp_path: Path) -> None:
        """`_as_int` must reject non-numeric types, not just unparseable strings."""
        _write_report(tmp_path, [_record("suite:root", tier="A") | {"duration_ms": None}, _record("cli:bregress")])
        assert em.load_run_steps(tmp_path)[0].duration_ms == 0

    def test_a_missing_report_directory_yields_no_junit(self, tmp_path: Path) -> None:
        assert em.load_junit(tmp_path / "absent") == {}

    def test_evidence_outside_the_repo_is_reported_absolutely(self, tmp_path: Path) -> None:
        (tmp_path / "cli_x.log").write_text("", encoding="utf-8")
        assert em.evidence_for("cli:x", tmp_path).startswith("/")

    def test_a_missing_makefile_yields_no_members(self, tmp_path: Path) -> None:
        assert em.makefile_check_members(tmp_path) == ()

    def test_a_makefile_without_check_all_yields_no_members(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("test:\n\techo hi\n", encoding="utf-8")
        assert em.makefile_check_members(tmp_path) == ()

    def test_undecodable_bytes_are_treated_as_absent_not_a_crash(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`UnicodeDecodeError` is a `ValueError`, not an `OSError` -- uncaught, it would
        escape as a raw traceback instead of the documented soft-degrade every other
        missing-file case gets."""
        (tmp_path / "Makefile").write_bytes(b"check-all: check-\xff\ntest:\n")
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            assert em.makefile_check_members(tmp_path) == ()
        assert any("treating it as absent" in r.getMessage() for r in caplog.records)

    def test_each_absent_floor_anchor_yields_none(self, tmp_path: Path) -> None:
        assert em._floor_from_pyproject(tmp_path / "pyproject.toml") is None
        assert em._floor_from_gate_script(tmp_path / "quality-gate.sh") is None
        assert em._floor_from_coveragerc(tmp_path / ".coveragerc") is None
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        assert em._floor_from_pyproject(tmp_path / "pyproject.toml") is None
        (tmp_path / "quality-gate.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        assert em._floor_from_gate_script(tmp_path / "quality-gate.sh") is None

    def test_an_unreadable_coveragerc_warns_and_yields_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / ".coveragerc").write_text("[report]\nfail_under = not-a-number\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            assert em._floor_from_coveragerc(tmp_path / ".coveragerc") is None
        assert any("coverage floor" in r.getMessage() for r in caplog.records)

    def test_a_missing_workflow_directory_yields_no_mapping(self, tmp_path: Path) -> None:
        assert em.derive_workflows(tmp_path) == {}

    def test_credential_derivations_need_the_runner(self, tmp_path: Path) -> None:
        """Every runner-derived helper degrades to empty rather than raising."""
        assert em.runner_env_gates(tmp_path) == {}
        assert em.smoke_credentials(tmp_path) == {}
        assert em._judge_credentials(tmp_path / "absent.ps1") == {}

    def test_a_runner_without_live_judges_yields_no_specs(self, tmp_path: Path) -> None:
        runner = tmp_path / "run.ps1"
        runner.write_text("Add-Result 'A' 'suite:x' 'PASS'\n", encoding="utf-8")
        assert em._judge_credentials(runner) == {}

    def test_build_sheets_without_a_runner_is_a_config_error(self, tmp_path: Path) -> None:
        _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
        with pytest.raises(em.MatrixConfigError, match="runner not found"):
            em.build_sheets(tmp_path, root=tmp_path, provenance=FIXED_PROVENANCE)

    def test_build_sheets_honors_a_custom_root_for_the_runner_too(self, tmp_path: Path, monkeypatch) -> None:
        """`root` must govern which runner is parsed, not just credentials/workflows/packages."""
        _write_report(tmp_path, [_record("suite:x", tier="C")])
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run_all_e2e.ps1").write_text("Add-Result 'C' 'suite:x' 'PASS'\n", encoding="utf-8")
        monkeypatch.setattr(em, "derive_live_credentials", lambda root: {})
        monkeypatch.setattr(em, "derive_workflows", lambda root: {})
        monkeypatch.setattr(em, "derive_packages", lambda root, workflows: ())
        sheets = em.build_sheets(tmp_path, root=tmp_path, provenance=FIXED_PROVENANCE)
        matrix = next(s for s in sheets if s.name == "Test Matrix")
        assert any(row[2] == "suite:x" for row in matrix.rows)

    def test_an_unresolvable_loop_variable_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """A `$x.name` loop whose collection cannot be found must say so, not drop steps."""
        source = "Add-Result 'A' 'suite:x' 'PASS'\nInvoke-CmdStep 'C' $q.name @('-m', 'x')\n"
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            em.parse_declared_steps(source)
        assert any("cannot resolve" in r.getMessage() for r in caplog.records)

    def test_an_empty_resolved_array_body_warns_and_yields_no_steps(self, caplog: pytest.LogCaptureFixture) -> None:
        """`$suites = @(\\n)` resolves (unlike an unresolvable collection) but is empty.

        A resolvable-but-empty collection previously produced zero steps from that loop with
        no diagnostic at all -- distinct from (and easier to miss than) the unresolvable case
        above, which already warned.
        """
        source = "Add-Result 'A' 'suite:x' 'PASS'\n$suites = @(\n)\nforeach ($s in $suites) {\n    Invoke-PytestStep 'A' $s.name\n}\n"
        with caplog.at_level(logging.WARNING, logger="tests._e2e_matrix"):
            declared = em.parse_declared_steps(source)
        assert any("empty array literal" in r.getMessage() for r in caplog.records)
        assert {step.name for step in declared} == {"suite:x"}

    def test_an_orphan_tier_is_a_policy_problem(self, declared: tuple[em.DeclaredStep, ...]) -> None:
        problems = em.policy_problems([em.RunStep("Z", declared[0].name, "PASS", "", 1)], declared)
        assert any("no declared step belongs to it" in p for p in problems)

    def test_parser_primitives_degrade_to_empty(self) -> None:
        """Every primitive returns a falsy value rather than raising on input it cannot read."""
        assert em._balanced_args_span("no array at all", 0) is None
        assert em._balanced_args_span("@( unterminated", 0) is None
        assert em._balanced_args("no array at all", 0) is None
        assert em._resolve_array_literal("nothing here", "missing") is None
        assert em._render_command(None) == ""
        assert em._render_command("$onlyVars") == "python $onlyVars"
        assert em._render_command("   ") == ""

    def test_judge_specs_need_the_runner(self, tmp_path: Path) -> None:
        assert em.runner_judge_specs(tmp_path / "absent.ps1") == {}
        empty = tmp_path / "run.ps1"
        empty.write_text("Add-Result 'A' 'suite:x' 'PASS'\n", encoding="utf-8")
        assert em.runner_judge_specs(empty) == {}

    def test_an_unparseable_positional_token_yields_blank(self) -> None:
        """A path built by something other than Join-Path must not be guessed at."""
        assert em._resolve_path_literal("$x = [IO.Path]::Combine($d, 'tests', 'integration')", "$x") == ""
        assert em._resolve_path_literal("", "$never_declared") == ""
        assert em._resolve_path_literal("anything", "'literal-value'") == "literal-value"


# ---------------------------------------------------------------------------
# The committed artifact's other renderings
# ---------------------------------------------------------------------------


def test_a_stale_csv_mirror_is_reported(tmp_path: Path) -> None:
    """The markdown used to be the only gated output, so a CSV could rot unnoticed."""
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    sheets = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
    out = tmp_path / "out"
    em.write_artifacts(sheets, out)
    target = out / em.CSV_DIR_NAME / em.csv_filename(sheets[0])
    target.write_text("Tier,Area\ntampered,row\n", encoding="utf-8")

    fresh, rendered = em.artifact_is_fresh(sheets, out)
    assert not fresh
    assert target.name in em.freshness_failure_message(rendered, out, sheets)


def test_an_orphan_csv_is_reported_stale(tmp_path: Path) -> None:
    """A CSV left behind by a renamed/removed sheet must not go undetected forever.

    `stale_csv_mirrors` used to iterate only the *current* sheets, never the directory, so
    it could never notice a file it never looked for.
    """
    _write_report(tmp_path, [_record("suite:root", tier="A"), _record("cli:bregress")])
    sheets = em.build_sheets(tmp_path, provenance=FIXED_PROVENANCE)
    out = tmp_path / "out"
    em.write_artifacts(sheets, out)
    orphan = out / em.CSV_DIR_NAME / "renamed_sheet.csv"
    orphan.write_text("stale content\n", encoding="utf-8")

    assert "renamed_sheet.csv" in em.stale_csv_mirrors(sheets, out)


def test_stale_csv_mirrors_skips_the_orphan_sweep_when_no_csv_directory_exists(tmp_path: Path) -> None:
    """Nothing has been written yet: the orphan sweep must not try to glob a missing directory.

    The sheet's own CSV is still correctly reported stale (it does not exist); only the
    *orphan* half of the check -- which globs `csv_dir` -- has anything to skip.
    """
    assert em.stale_csv_mirrors([em.Sheet(name="S", columns=("A",))], tmp_path) == ["s.csv"]


def test_control_characters_never_reach_a_cell() -> None:
    """openpyxl rejects them outright, so one stray byte would break the whole workbook."""
    assert em.safe_cell("a\x00b\x1bc") == "a b c"


# ---------------------------------------------------------------------------
# The interpreter shim (no test existed; it broke two Tier-A steps once)
# ---------------------------------------------------------------------------


def test_sitecustomize_is_silent_off_windows() -> None:
    """The shim must print nothing on a platform that has no WMI to shim.

    It once warned unconditionally when `platform._wmi_query` was absent - which is every
    non-Windows interpreter - so its breadcrumb landed in the output of every child process
    the runner started, and broke a test asserting a subprocess prints only its version.
    Nothing else in the repo covers this file: it is never imported, so it does not even
    appear in the `--cov=scripts` report.
    """
    shim_dir = ROOT / "scripts" / "e2e_shims"
    env = {**os.environ, "PYTHONPATH": str(shim_dir)}
    result = subprocess.run(
        [sys.executable, "-c", "print('only-this')"],
        capture_output=True,
        text=True,
        env=env,
        timeout=DEFAULT_SUBPROCESS_CONFIG.shim_probe_timeout_seconds,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "only-this"
    assert result.stderr == "", f"the shim wrote to stderr: {result.stderr!r}"


# ---------------------------------------------------------------------------
# CLI: the entry point CI measures but nothing exercised
# ---------------------------------------------------------------------------


class TestCommandLine:
    """`main()` had no tests at all, despite being inside the coverage target CI enforces."""

    @staticmethod
    def _seed(tmp_path: Path) -> tuple[Path, Path]:
        report, out = tmp_path / "report", tmp_path / "out"
        _write_report(report, [_record("suite:root", tier="A"), _record("cli:bregress")])
        return report, out

    def test_update_writes_the_artifact_and_check_then_passes(self, tmp_path: Path, capsys) -> None:
        report, out = self._seed(tmp_path)
        assert main(["--update", "--report", str(report), "--out", str(out)]) == EXIT_OK
        assert (out / em.ARTIFACT_DOC_NAME).is_file()
        capsys.readouterr()
        assert main(["--check", "--report", str(report), "--out", str(out)]) == EXIT_OK
        assert "is fresh" in capsys.readouterr().out

    def test_check_reports_a_stale_artifact(self, tmp_path: Path, capsys) -> None:
        report, out = self._seed(tmp_path)
        main(["--update", "--report", str(report), "--out", str(out)])
        (out / em.ARTIFACT_DOC_NAME).write_text("# tampered\n", encoding="utf-8")
        capsys.readouterr()
        assert main(["--check", "--report", str(report), "--out", str(out)]) == EXIT_PROBLEM
        assert "stale" in capsys.readouterr().err

    def test_a_missing_report_is_a_usage_error(self, tmp_path: Path, capsys) -> None:
        """Exit 2 must come from the exception's type, not from matching its prose."""
        assert main(["--check", "--report", str(tmp_path / "absent"), "--out", str(tmp_path)]) == EXIT_USAGE_ERROR
        assert "no run report" in capsys.readouterr().err

    def test_an_undeclared_step_is_a_problem_not_a_usage_error(self, tmp_path: Path, capsys) -> None:
        report, out = tmp_path / "report", tmp_path / "out"
        _write_report(report, [_record("cli:invented"), _record("suite:root", tier="A")])
        assert main(["--update", "--report", str(report), "--out", str(out)]) == EXIT_PROBLEM
        assert "not declared" in capsys.readouterr().err

    def test_verbose_enables_debug_logging(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        report, out = self._seed(tmp_path)
        with caplog.at_level(logging.DEBUG, logger="tests._e2e_matrix"):
            main(["--update", "--report", str(report), "--out", str(out), "-v"])
        assert any(r.levelno == logging.DEBUG for r in caplog.records)

    def test_the_committed_builder_is_what_the_cli_uses(self, tmp_path: Path) -> None:
        """One builder for `--update`, `--check` and the freshness test, redaction included."""
        report, _ = self._seed(tmp_path)
        sheets, _ = build_committed_sheets(report, sha="0" * 40, stamp=FIXED_STAMP)
        assert sheets[0].name == "Test Matrix"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _display_path(path: Path) -> str:
    """Repo-relative when the path is inside the repo, absolute otherwise.

    `--out` may point anywhere; a bare `relative_to` raised `ValueError` and took the whole
    command down after it had already written every file.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_committed_sheets(
    report_dir: Path = em.DEFAULT_REPORT_DIR, *, sha: str | None = None, stamp: str | None = None
) -> tuple[tuple[em.Sheet, ...], em.Provenance]:
    """The sheets exactly as the committed artifact is written, with the provenance used.

    One entry point on purpose. `--update` used to build *with* the redaction callable while
    the freshness test built *without* it, so an artifact that had genuinely redacted a
    credential would compare unequal and report stale forever. Anything that renders the
    committed artifact must go through here.

    The provenance is returned alongside the sheets so a caller that also needs its
    ``generated_at`` (the xlsx writer's pinned timestamp, say) can use the value that was
    actually rendered instead of re-deriving it or scraping it back out of a rendered row.
    """
    provenance = _provenance(sha, stamp)
    return em.build_sheets(report_dir, provenance=provenance, scrub=_load_scrubber()), provenance


def _git(*args: str) -> str:
    """A git value for provenance, or an empty string outside a checkout."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=DEFAULT_SUBPROCESS_CONFIG.git_timeout_seconds,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git %s failed (%s); provenance field left blank", " ".join(args), exc)
        return ""


def _to_utc_iso(stamp: str) -> str:
    """Normalize an ISO 8601 timestamp to a UTC offset, preserving precision.

    ``git log --format=%cI`` carries the *committer's* local offset (e.g. ``-04:00``), not
    UTC, even though the Provenance sheet labels this column "Generated at (UTC)" and
    ``_e2e_matrix_xlsx.parse_stamp`` derives the workbook's pinned ZIP/``docProps``
    timestamps from this same string. Normalizing once here, at the source, means both
    consumers get a value that matches its own label instead of each needing its own fix.
    """
    if not stamp:
        return stamp
    return dt.datetime.fromisoformat(stamp).astimezone(dt.timezone.utc).isoformat()


def _provenance(sha: str | None = None, stamp: str | None = None) -> em.Provenance:
    """Run identity. Volatile values are overridable so a render can be reproduced."""
    return em.Provenance(
        sha=sha or _git("rev-parse", "HEAD"),
        branch=_git("rev-parse", "--abbrev-ref", "HEAD"),
        generated_at=_to_utc_iso(stamp or _git("log", "-1", "--format=%cI")),
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

    try:
        sheets, provenance = build_committed_sheets(args.report, sha=args.sha, stamp=args.timestamp)
    except em.MatrixError as exc:
        print(f"e2e-matrix: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR if isinstance(exc, em.MatrixConfigError) else EXIT_PROBLEM

    if args.check:
        fresh, rendered = em.artifact_is_fresh(sheets, args.out)
        if not fresh:
            print(em.freshness_failure_message(rendered, args.out, sheets), file=sys.stderr)
            return EXIT_PROBLEM
        print(f"{(args.out / em.ARTIFACT_DOC_NAME).as_posix()} is fresh")
        return EXIT_OK

    written = em.write_artifacts(sheets, args.out)
    try:
        from tests import _e2e_matrix_xlsx as xw

        written.append(xw.write_workbook(sheets, args.out / em.WORKBOOK_FILENAME, stamp_iso=provenance.generated_at))
    except ImportError as exc:
        logger.warning("workbook not written: %s", exc)
    for path in written:
        print(_display_path(path))
    return EXIT_OK


def _load_scrubber() -> Callable[[str], str] | None:
    """Reuse the smokes' redaction so committed cells cannot carry a credential."""
    smokes = ROOT / em.SMOKES_DIR_NAME
    if str(smokes) not in sys.path:
        sys.path.append(str(smokes))
    try:
        import _smoke_lib
    except ImportError as exc:  # pragma: no cover - the smokes ship with the repo
        # A silent None here means build_committed_sheets renders the run's raw output --
        # including anything a live step printed -- into a *committed* file with no
        # redaction at all. em.derive_live_credentials degrades the same way and already
        # warns; this path must too.
        logger.warning("redaction unavailable (%s); committed cells will not be scrubbed", exc)
        return None
    secrets = [value for name, value in os.environ.items() if _is_secret_name(name) and value]
    return lambda text: _smoke_lib.redact(text, secrets)


#: Suffixes that mark a variable's *value* as unsafe to render, for variables the matrix
#: does not otherwise know about.
_SECRET_NAME_SUFFIXES = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_BASE_URL")


def _is_secret_name(name: str) -> bool:
    """Whether this variable's *value* must never appear in a committed cell.

    The suffix list alone is not enough, and the gap was real: ``AWS_ACCESS_KEY_ID`` ends in
    ``_ID``, so a heuristic-only policy left the one credential the Bedrock step gates on
    unredacted. Every variable named by a live step is therefore treated as sensitive too --
    derived from the same declarations the Credentials sheet is built from, so a new live
    step is covered the moment it is added rather than whenever someone remembers to extend
    a suffix list.
    """
    return name.endswith(_SECRET_NAME_SUFFIXES) or name in _live_step_variables()


@lru_cache(maxsize=1)
def _live_step_variables() -> frozenset[str]:
    """Every environment variable a live step gates on, from the code that declares them."""
    return frozenset(name for names in em.derive_live_credentials(ROOT).values() for name in names)


if __name__ == "__main__":
    sys.exit(main())
