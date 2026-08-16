"""Unit tests for the skill validator module."""

from __future__ import annotations

import json
from pathlib import Path

from ..skill_validator import (
    BEHAVIORAL_TYPES,
    WORKDIR,
    check_structural,
    first_path_token,
    grade,
    grade_command_exit_zero,
    grade_exit_nonzero,
    grade_exit_zero,
    grade_file_contains,
    grade_file_exists,
    grade_output_contains,
    load_evals,
    parse_frontmatter,
)


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
