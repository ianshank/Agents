"""Unit tests for the skill validator module."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .. import skill_validator
from ..skill_validator import (
    BEHAVIORAL_TYPES,
    WORKDIR,
    check_behavioral,
    check_structural,
    first_path_token,
    get_validator_module_path,
    grade,
    grade_command_exit_zero,
    grade_exit_nonzero,
    grade_exit_zero,
    grade_file_contains,
    grade_file_exists,
    grade_idempotent,
    grade_output_contains,
    load_evals,
    parse_frontmatter,
)
from ..skill_validator import (
    _run_one_eval as run_one_eval,
)
from ..skill_validator import (
    _validate_eval_shape as validate_eval_shape,
)


def test_get_validator_module_path_returns_this_files_directory() -> None:
    """get_validator_module_path() returns the directory containing skill_validator.py."""
    path = get_validator_module_path()
    assert Path(path).is_dir()
    assert (Path(path) / "skill_validator.py").is_file()


class TestParsesFrontmatter:
    """Tests for parse_frontmatter()."""

    def test_valid_yaml_frontmatter(self, tmp_path: Path) -> None:
        """YAML frontmatter is parsed correctly."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: A test skill\n---\n# Content\n")
        fm, nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert fm["name"] == "test-skill"
        assert fm["description"] == "A test skill"
        assert nlines == 5

    def test_fallback_frontmatter_parsing(self, tmp_path: Path) -> None:
        """Fallback parser handles YAML parsing failures."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: A test skill\n---\nContent\n")
        fm, _nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert fm["name"] == "test-skill"

    def test_yaml_syntax_error_falls_back_to_manual_parser(self, tmp_path: Path) -> None:
        """A block that raises inside yaml.safe_load (not just a wrong shape) still parses."""
        skill_md = tmp_path / "SKILL.md"
        # `[unterminated` is invalid flow-sequence syntax -> yaml.safe_load raises,
        # exercising the `except Exception: pass` branch before the manual fallback.
        skill_md.write_text("---\nname: test-skill\nbad: [unterminated\n---\nContent\n")
        fm, _nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert fm["name"] == "test-skill"

    def test_yaml_non_dict_result_falls_back_to_manual_parser(self, tmp_path: Path) -> None:
        """A block that parses to a non-dict (e.g. a bare scalar) also falls back."""
        skill_md = tmp_path / "SKILL.md"
        # `justastring` is valid YAML but yields a str, not a dict -- the isinstance
        # check fails without raising, falling through to the manual line-scanner.
        skill_md.write_text("---\njustastring\n---\nContent\n")
        fm, _nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert fm == {}

    def test_manual_fallback_skips_blank_lines_and_folds_continuations(self, tmp_path: Path) -> None:
        """The manual line-scanner (reached only on fallback) skips blanks and folds indents."""
        skill_md = tmp_path / "SKILL.md"
        # `bad: [x` is invalid YAML flow syntax, forcing the manual fallback for the
        # whole block -- including the blank-line skip and the folded-continuation join,
        # neither of which the primary yaml.safe_load path ever reaches.
        skill_md.write_text(
            "---\nname: test-skill\n\ndescription: a long description that\n  continues here\nbad: [x\n---\nContent\n"
        )
        fm, _nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert fm["name"] == "test-skill"
        assert fm["description"] == "a long description that continues here"

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        """Missing frontmatter returns None."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# No frontmatter here\n")
        fm, nlines = parse_frontmatter(str(skill_md))
        assert fm is None
        assert nlines == 1

    def test_folded_continuation_lines(self, tmp_path: Path) -> None:
        """Fallback parser handles folded continuation lines."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: A long description that\n  continues on the next line\n---\nContent\n")
        fm, _nlines = parse_frontmatter(str(skill_md))
        assert fm is not None
        assert "long description" in fm.get("description", "")


class TestLoadsEvals:
    """Tests for load_evals()."""

    def test_loads_valid_evals_json(self, tmp_path: Path) -> None:
        """Valid evals.json loads correctly."""
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": [{"id": "test"}]}))
        errs: list[str] = []
        spec = load_evals(str(tmp_path), "evals.json", errs)
        assert spec is not None
        assert spec["evals"] == [{"id": "test"}]
        assert errs == []

    def test_missing_evals_file(self, tmp_path: Path) -> None:
        """Missing evals.json returns None without error."""
        errs: list[str] = []
        spec = load_evals(str(tmp_path), "evals.json", errs)
        assert spec is None
        assert errs == []

    def test_invalid_json_evals_file(self, tmp_path: Path) -> None:
        """Invalid JSON in evals.json reports error."""
        evals_json = tmp_path / "evals.json"
        evals_json.write_text("{invalid json}")
        errs: list[str] = []
        spec = load_evals(str(tmp_path), "evals.json", errs)
        assert spec is None
        assert any("cannot parse" in err for err in errs)

    def test_evals_must_be_object(self, tmp_path: Path) -> None:
        """Evals must be a JSON object, not a list."""
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps([{"id": "test"}]))
        errs: list[str] = []
        spec = load_evals(str(tmp_path), "evals.json", errs)
        assert spec is None
        assert any("must be a JSON object" in err for err in errs)


class TestFirstPathToken:
    """Tests for first_path_token()."""

    def test_finds_first_path_token(self) -> None:
        """Extracts first path token from command."""
        assert first_path_token("ls -la scripts/validate.py") == "scripts/validate.py"
        assert first_path_token("echo hello") is None
        assert first_path_token("--flag scripts/file.py") == "scripts/file.py"

    def test_ignores_tokens_with_leading_dash(self) -> None:
        """Finds path tokens; tokens starting with - are skipped."""
        assert first_path_token("-f /path/file") == "/path/file"
        assert first_path_token("--something echo") is None


class TestCheckStructural:
    """Tests for check_structural()."""

    def test_valid_skill_structure(self, tmp_path: Path) -> None:
        """Valid skill structure passes."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: When to use this test skill\n---\n# Content\n")
        errs, _warns = check_structural(str(tmp_path), "evals.json")
        assert errs == []

    def test_missing_skill_md(self, tmp_path: Path) -> None:
        """Missing SKILL.md is an error."""
        errs, _warns = check_structural(str(tmp_path), "evals.json")
        assert any("missing" in err.lower() for err in errs)

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        """Missing frontmatter is an error."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# No frontmatter\n")
        errs, _warns = check_structural(str(tmp_path), "evals.json")
        assert any("YAML frontmatter" in err for err in errs)

    def test_missing_name_field(self, tmp_path: Path) -> None:
        """Missing name field is an error."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\ndescription: Test\n---\nContent\n")
        errs, _warns = check_structural(str(tmp_path), "evals.json")
        assert any("name" in err.lower() for err in errs)

    def test_missing_description_field(self, tmp_path: Path) -> None:
        """Missing description field is an error."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\n---\nContent\n")
        errs, _warns = check_structural(str(tmp_path), "evals.json")
        assert any("description" in err.lower() for err in errs)

    def test_description_lacking_trigger_cue(self, tmp_path: Path) -> None:
        """Description lacking 'when to use' cue is a warning."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: A short description\n---\nContent\n")
        errs, warns = check_structural(str(tmp_path), "evals.json")
        assert errs == []
        assert any("when to use" in w.lower() for w in warns)

    def test_name_not_lowercase_hyphen_warns(self, tmp_path: Path) -> None:
        """A name that isn't lowercase-hyphen (e.g. contains underscores) warns."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: Test_Skill\ndescription: Use this when testing things\n---\nContent\n")
        errs, warns = check_structural(str(tmp_path), "evals.json")
        assert errs == []
        assert any("lowercase-hyphen" in w for w in warns)

    def test_name_matching_directory_has_no_dir_mismatch_warning(self, tmp_path: Path) -> None:
        """When the skill dir basename matches the frontmatter name, no mismatch warning fires."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: my-skill\ndescription: Use this when testing things\n---\nContent\n")
        _errs, warns = check_structural(str(skill_dir), "evals.json")
        assert not any("!= skill name" in w for w in warns)

    def test_long_description_with_trigger_cue_has_no_warnings(self, tmp_path: Path) -> None:
        """A sufficiently long description with a trigger cue produces zero warnings."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_md = skill_dir / "SKILL.md"
        long_desc = "Use this skill whenever the user needs to validate something thoroughly and completely"
        skill_md.write_text(f"---\nname: test-skill\ndescription: {long_desc}\n---\nContent\n")
        errs, warns = check_structural(str(skill_dir), "evals.json")
        assert errs == []
        assert warns == []

    def test_long_skill_md_warns(self, tmp_path: Path) -> None:
        """SKILL.md over 500 lines gets a move-detail-to-references warning."""
        skill_md = tmp_path / "SKILL.md"
        body = "\n".join(f"line {i}" for i in range(510))
        skill_md.write_text(f"---\nname: test-skill\ndescription: Use this when testing things\n---\n{body}\n")
        _errs, warns = check_structural(str(tmp_path), "evals.json")
        assert any("500" in w for w in warns)

    def test_evals_not_a_list_produces_no_file_ref_warnings(self, tmp_path: Path) -> None:
        """A malformed (non-list) 'evals' value degrades quietly instead of crashing."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: Use this when testing things\n---\nContent\n")
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": "not-a-list"}))
        errs, warns = check_structural(str(tmp_path), "evals.json")
        assert errs == []
        assert not any("missing file" in w for w in warns)

    def test_eval_referencing_missing_script_warns(self, tmp_path: Path) -> None:
        """An eval's run/setup command referencing an absent scripts/ file warns."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: Use this when testing things\n---\nContent\n")
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": [{"id": "e1", "run": "python scripts/missing.py"}]}))
        _errs, warns = check_structural(str(tmp_path), "evals.json")
        assert any("missing file" in w and "scripts/missing.py" in w for w in warns)

    def test_eval_referencing_existing_script_has_no_warning(self, tmp_path: Path) -> None:
        """A run/setup command referencing a scripts/ file that DOES exist warns about nothing."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test-skill\ndescription: Use this when testing things\n---\nContent\n")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "present.py").write_text("# present\n")
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": [{"id": "e1", "run": "python scripts/present.py"}]}))
        _errs, warns = check_structural(str(tmp_path), "evals.json")
        assert not any("missing file" in w for w in warns)


class TestGradeExitZero:
    """Tests for grade_exit_zero()."""

    def test_passes_when_exit_code_is_zero(self) -> None:
        """Exit code 0 passes."""
        passed, evidence = grade_exit_zero({}, run_rc=0, run_out="", has_run=True, skill_dir=".", timeout=10)
        assert passed is True
        assert "exit=0" in evidence

    def test_fails_when_exit_code_nonzero(self) -> None:
        """Non-zero exit code fails."""
        passed, evidence = grade_exit_zero({}, run_rc=1, run_out="", has_run=True, skill_dir=".", timeout=10)
        assert passed is False
        assert "exit=1" in evidence

    def test_fails_when_no_run_command(self) -> None:
        """No run command fails."""
        passed, _evidence = grade_exit_zero({}, run_rc=0, run_out="", has_run=False, skill_dir=".", timeout=10)
        assert passed is False


class TestGradeExitNonzero:
    """Tests for grade_exit_nonzero()."""

    def test_passes_when_exit_code_nonzero(self) -> None:
        """Non-zero exit code passes."""
        passed, _evidence = grade_exit_nonzero({}, run_rc=1, run_out="", has_run=True, skill_dir=".", timeout=10)
        assert passed is True

    def test_fails_when_exit_code_zero(self) -> None:
        """Exit code 0 fails."""
        passed, _evidence = grade_exit_nonzero({}, run_rc=0, run_out="", has_run=True, skill_dir=".", timeout=10)
        assert passed is False

    def test_fails_when_no_run_command(self) -> None:
        """No run command fails, regardless of run_rc."""
        passed, evidence = grade_exit_nonzero({}, run_rc=1, run_out="", has_run=False, skill_dir=".", timeout=10)
        assert passed is False
        assert "no 'run'" in evidence


class TestGradeOutputContains:
    """Tests for grade_output_contains()."""

    def test_passes_when_output_contains_needle(self) -> None:
        """Output containing needle passes."""
        passed, _evidence = grade_output_contains(
            {"contains": "hello"},
            run_rc=0,
            run_out="hello world",
            has_run=True,
            skill_dir=".",
            timeout=10,
        )
        assert passed is True

    def test_fails_when_output_lacks_needle(self) -> None:
        """Output lacking needle fails."""
        passed, _evidence = grade_output_contains(
            {"contains": "goodbye"},
            run_rc=0,
            run_out="hello world",
            has_run=True,
            skill_dir=".",
            timeout=10,
        )
        assert passed is False

    def test_fails_when_no_run_command(self) -> None:
        """No run command fails, regardless of run_out content."""
        passed, evidence = grade_output_contains(
            {"contains": "hello"},
            run_rc=0,
            run_out="hello world",
            has_run=False,
            skill_dir=".",
            timeout=10,
        )
        assert passed is False
        assert "no 'run'" in evidence


class TestGradeFileExists:
    """Tests for grade_file_exists()."""

    def test_passes_when_file_exists(self, tmp_path: Path) -> None:
        """Existing file passes."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("content")
        passed, evidence = grade_file_exists(
            {"path": "test.txt"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=str(tmp_path),
            timeout=10,
        )
        assert passed is True
        assert "exists" in evidence

    def test_fails_when_file_absent(self, tmp_path: Path) -> None:
        """Absent file fails."""
        passed, evidence = grade_file_exists(
            {"path": "nonexistent.txt"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=str(tmp_path),
            timeout=10,
        )
        assert passed is False
        assert "absent" in evidence


class TestGradeFileContains:
    """Tests for grade_file_contains()."""

    def test_passes_when_file_contains_needle(self, tmp_path: Path) -> None:
        """File containing needle passes."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("hello world")
        passed, _evidence = grade_file_contains(
            {"path": "test.txt", "contains": "hello"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=str(tmp_path),
            timeout=10,
        )
        assert passed is True

    def test_fails_when_file_lacks_needle(self, tmp_path: Path) -> None:
        """File lacking needle fails."""
        testfile = tmp_path / "test.txt"
        testfile.write_text("goodbye world")
        passed, _evidence = grade_file_contains(
            {"path": "test.txt", "contains": "hello"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=str(tmp_path),
            timeout=10,
        )
        assert passed is False

    def test_fails_when_file_unreadable(self, tmp_path: Path) -> None:
        """Unreadable file fails gracefully."""
        passed, evidence = grade_file_contains(
            {"path": "nonexistent.txt", "contains": "hello"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=str(tmp_path),
            timeout=10,
        )
        assert passed is False
        assert "cannot read" in evidence


class TestGradeCommandExitZero:
    """Tests for grade_command_exit_zero()."""

    def test_passes_when_command_succeeds(self) -> None:
        """Command with exit 0 passes."""
        passed, _evidence = grade_command_exit_zero(
            {"cmd": "true"},
            run_rc=0,
            run_out="",
            has_run=False,
            skill_dir=".",
            timeout=10,
        )
        assert passed is True

    def test_fails_when_command_fails(self) -> None:
        """Command with non-zero exit fails."""
        passed, _evidence = grade_command_exit_zero(
            {"cmd": "false"},
            run_rc=0,
            run_out="",
            has_run=False,
            skill_dir=".",
            timeout=10,
        )
        assert passed is False

    def test_fails_when_command_times_out(self, monkeypatch) -> None:
        """A command that exceeds the timeout fails with a timeout message, not a raise."""

        def _raise_timeout(cmd, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(skill_validator, "_run_eval", _raise_timeout)
        passed, evidence = grade_command_exit_zero(
            {"cmd": "sleep 100"},
            run_rc=0,
            run_out="",
            has_run=False,
            skill_dir=".",
            timeout=1,
        )
        assert passed is False
        assert "timed out" in evidence


class TestGradeIdempotent:
    """Tests for grade_idempotent()."""

    def test_fails_when_no_run(self) -> None:
        """No run command at all fails."""
        passed, evidence = grade_idempotent({}, run_rc=0, run_out="x", has_run=False, skill_dir=".", timeout=10)
        assert passed is False
        assert "no 'run'" in evidence

    def test_fails_when_run_cmd_missing(self) -> None:
        """has_run True but run_cmd is None/empty still fails cleanly."""
        passed, evidence = grade_idempotent(
            {}, run_rc=0, run_out="x", has_run=True, skill_dir=".", timeout=10, run_cmd=None
        )
        assert passed is False
        assert "run command is missing" in evidence

    def test_passes_when_second_run_matches_first(self) -> None:
        """Identical stdout across two runs of a deterministic command passes."""
        passed, evidence = grade_idempotent(
            {},
            run_rc=0,
            run_out="hello\n",
            has_run=True,
            skill_dir=".",
            timeout=10,
            run_cmd="echo hello",
        )
        assert passed is True
        assert "matches" in evidence

    def test_fails_when_second_run_exit_code_differs(self) -> None:
        """A second run with a different exit code fails, even if stdout matches."""
        passed, evidence = grade_idempotent(
            {},
            run_rc=1,  # first run's rc; second run's `true` will exit 0, mismatching
            run_out="",
            has_run=True,
            skill_dir=".",
            timeout=10,
            run_cmd="true",
        )
        assert passed is False
        assert "second run failed with exit" in evidence

    def test_fails_when_second_run_stdout_differs(self) -> None:
        """A second run with different stdout fails, even with a matching exit code."""
        passed, evidence = grade_idempotent(
            {},
            run_rc=0,
            run_out="not what echo produces",
            has_run=True,
            skill_dir=".",
            timeout=10,
            run_cmd="echo hello",
        )
        assert passed is False
        assert "mismatch" in evidence

    def test_fails_on_timeout(self, monkeypatch) -> None:
        """The second run timing out fails with a timeout message, not a raise."""

        def _raise_timeout(cmd, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(skill_validator, "_run_eval", _raise_timeout)
        passed, evidence = grade_idempotent(
            {},
            run_rc=0,
            run_out="hello\n",
            has_run=True,
            skill_dir=".",
            timeout=1,
            run_cmd="echo hello",
        )
        assert passed is False
        assert "timed out" in evidence


class TestGradeGeneric:
    """Tests for grade() dispatcher."""

    def test_routes_to_correct_grader(self) -> None:
        """grade() routes to the correct grader by type."""
        result = grade(
            {"type": "exit_zero", "text": "should exit cleanly"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=".",
            timeout=10,
        )
        assert result["passed"] is True

    def test_unknown_assertion_type_fails(self) -> None:
        """Unknown assertion type fails."""
        result = grade(
            {"type": "unknown_type"},
            run_rc=0,
            run_out="",
            has_run=True,
            skill_dir=".",
            timeout=10,
        )
        assert result["passed"] is False
        assert "unknown" in result["evidence"]


class TestBehavioralTypes:
    """Tests for BEHAVIORAL_TYPES constant."""

    def test_behavioral_types_is_set(self) -> None:
        """BEHAVIORAL_TYPES is defined and non-empty."""
        assert isinstance(BEHAVIORAL_TYPES, set)
        assert len(BEHAVIORAL_TYPES) > 0
        assert "exit_zero" in BEHAVIORAL_TYPES
        assert "output_contains" in BEHAVIORAL_TYPES


class TestWorkdirConstant:
    """Tests for WORKDIR constant."""

    def test_workdir_is_defined(self) -> None:
        """WORKDIR constant is defined."""
        assert isinstance(WORKDIR, str)
        assert len(WORKDIR) > 0
        assert WORKDIR == ".skill-validation"


class TestValidateEvalShape:
    """Tests for _validate_eval_shape()."""

    def test_no_assertions_returns_false_and_errors(self) -> None:
        """An eval with zero assertions must be skipped entirely."""
        errs: list[str] = []
        ok = validate_eval_shape("e1", [], has_run=True, errs=errs)
        assert ok is False
        assert any("no assertions" in e for e in errs)

    def test_no_run_and_no_command_exit_zero_still_true_but_errors(self) -> None:
        """Assertions present but nothing executes: not skipped, but flagged."""
        errs: list[str] = []
        asserts = [{"type": "file_exists", "path": "x"}]
        ok = validate_eval_shape("e1", asserts, has_run=False, errs=errs)
        assert ok is True  # still graded -- file_exists can run without a 'run' command
        assert any("executes nothing" in e for e in errs)

    def test_command_exit_zero_assertion_counts_as_executing(self) -> None:
        """A command_exit_zero assertion satisfies the 'executes nothing' check on its own."""
        errs: list[str] = []
        asserts = [{"type": "command_exit_zero", "cmd": "true"}]
        ok = validate_eval_shape("e1", asserts, has_run=False, errs=errs)
        assert ok is True
        assert not any("executes nothing" in e for e in errs)

    def test_only_existence_assertions_still_true_but_errors(self) -> None:
        """Assertions present, something executes, but none are behavioral: flagged, not skipped."""
        errs: list[str] = []
        asserts = [{"type": "file_exists", "path": "x"}]
        ok = validate_eval_shape("e1", asserts, has_run=True, errs=errs)
        assert ok is True
        assert any("add a behavioral assertion" in e for e in errs)

    def test_valid_shape_returns_true_with_no_errors(self) -> None:
        """A well-formed eval (has_run + a behavioral assertion) reports no errors."""
        errs: list[str] = []
        asserts = [{"type": "exit_zero"}]
        ok = validate_eval_shape("e1", asserts, has_run=True, errs=errs)
        assert ok is True
        assert errs == []


class TestRunOneEval:
    """Tests for _run_one_eval()."""

    def test_skipped_eval_returns_none(self, tmp_path: Path) -> None:
        """An eval failing _validate_eval_shape (no assertions) returns None, not a record."""
        errs: list[str] = []
        ev = {"id": "e1", "run": "echo hi", "assertions": []}
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is None
        assert any("no assertions" in e for e in errs)

    def test_passing_run_produces_a_result_record(self, tmp_path: Path) -> None:
        """A run that succeeds and clears its assertion returns a populated record."""
        errs: list[str] = []
        ev = {
            "id": "e1",
            "prompt": "say hello",
            "run": "echo hello",
            "assertions": [{"type": "output_contains", "contains": "hello"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is not None
        assert result["eval_id"] == "e1"
        assert result["prompt"] == "say hello"
        assert result["expectations"][0]["passed"] is True
        assert errs == []

    def test_failing_assertion_is_recorded_in_errs(self, tmp_path: Path) -> None:
        """A run whose assertion fails still returns a record, with the failure in errs."""
        errs: list[str] = []
        ev = {
            "id": "e1",
            "run": "echo hello",
            "assertions": [{"type": "output_contains", "contains": "goodbye"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is not None
        assert result["expectations"][0]["passed"] is False
        assert any("e1" in e for e in errs)

    def test_setup_failure_skips_the_eval(self, tmp_path: Path) -> None:
        """A non-zero-exit setup command aborts the eval before run/grade."""
        errs: list[str] = []
        ev = {
            "id": "e1",
            "setup": "exit 1",
            "run": "echo hello",
            "assertions": [{"type": "exit_zero"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is None
        assert any("setup failed" in e for e in errs)

    def test_setup_success_continues_to_run(self, tmp_path: Path) -> None:
        """A zero-exit setup command does not abort the eval -- run/grade still happen."""
        errs: list[str] = []
        ev = {
            "id": "e1",
            "setup": "true",
            "run": "echo hello",
            "assertions": [{"type": "output_contains", "contains": "hello"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is not None
        assert result["expectations"][0]["passed"] is True
        assert errs == []

    def test_no_run_command_still_grades_command_exit_zero_assertions(self, tmp_path: Path) -> None:
        """has_run False (no 'run' key) with a command_exit_zero assertion still grades."""
        errs: list[str] = []
        ev = {
            "id": "e1",
            "assertions": [{"type": "command_exit_zero", "cmd": "true"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=10, errs=errs)
        assert result is not None
        assert result["expectations"][0]["passed"] is True
        assert not any("run timed out" in e for e in errs)

    def test_setup_timeout_skips_the_eval(self, tmp_path: Path, monkeypatch) -> None:
        """A setup command that times out aborts the eval, not just the run command."""

        def _raise_timeout(cmd, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(skill_validator, "_run_eval", _raise_timeout)
        errs: list[str] = []
        ev = {
            "id": "e1",
            "setup": "sleep 100",
            "run": "echo hello",
            "assertions": [{"type": "exit_zero"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=1, errs=errs)
        assert result is None
        assert any("setup timed out" in e for e in errs)

    def test_run_timeout_still_produces_a_record_with_124(self, tmp_path: Path, monkeypatch) -> None:
        """A run that times out is graded as a failure (rc=124), not silently dropped."""

        def _raise_timeout(cmd, cwd, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        monkeypatch.setattr(skill_validator, "_run_eval", _raise_timeout)
        errs: list[str] = []
        ev = {
            "id": "e1",
            "run": "sleep 100",
            "assertions": [{"type": "exit_zero"}],
        }
        result = run_one_eval(ev, str(tmp_path), timeout=1, errs=errs)
        assert result is not None
        assert result["expectations"][0]["passed"] is False
        assert any("run timed out" in e for e in errs)


class TestCheckBehavioral:
    """Tests for check_behavioral()."""

    def test_missing_evals_file_reports_error(self, tmp_path: Path) -> None:
        """No evals.json at all is a clean error, not a crash."""
        errs = check_behavioral(str(tmp_path), "evals.json", timeout=10)
        assert any("needs a parseable" in e for e in errs)

    def test_passing_eval_writes_grading_json(self, tmp_path: Path) -> None:
        """An end-to-end passing eval writes results to WORKDIR/grading.json."""
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(
            json.dumps(
                {
                    "evals": [
                        {
                            "id": "e1",
                            "run": "echo hello",
                            "assertions": [{"type": "output_contains", "contains": "hello"}],
                        }
                    ]
                }
            )
        )
        errs = check_behavioral(str(tmp_path), "evals.json", timeout=10)
        assert errs == []
        grading_path = tmp_path / WORKDIR / "grading.json"
        assert grading_path.is_file()
        payload = json.loads(grading_path.read_text())
        assert payload["results"][0]["eval_id"] == "e1"
        assert payload["results"][0]["expectations"][0]["passed"] is True

    def test_skipped_eval_is_excluded_from_results_but_recorded_in_errs(self, tmp_path: Path) -> None:
        """An eval with no assertions is dropped from results, not silently ignored."""
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": [{"id": "e1", "run": "echo hi", "assertions": []}]}))
        errs = check_behavioral(str(tmp_path), "evals.json", timeout=10)
        assert any("no assertions" in e for e in errs)
        grading_path = tmp_path / WORKDIR / "grading.json"
        payload = json.loads(grading_path.read_text())
        assert payload["results"] == []

    def test_rerun_clears_stale_workdir_contents(self, tmp_path: Path) -> None:
        """WORKDIR is rebuilt each run, so a stale file from a prior run doesn't linger."""
        work = tmp_path / WORKDIR
        work.mkdir()
        stale = work / "stale.txt"
        stale.write_text("leftover from a previous run")
        evals_json = tmp_path / "evals.json"
        evals_json.write_text(json.dumps({"evals": []}))
        check_behavioral(str(tmp_path), "evals.json", timeout=10)
        assert not stale.exists()
