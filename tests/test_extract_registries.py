"""Tests for scripts/extract_registries.py and scripts/check_readme_registries.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts directory is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_readme_registries  # noqa: E402
import extract_registries  # noqa: E402


class TestDiscoverRegistries:
    """Unit tests for AST registry discovery."""

    def test_discover_registries_from_annotated_assignments(self, tmp_path: Path) -> None:
        plugins_code = """
from eval_harness.core.registry import Registry

SCORERS: Registry[Scorer] = Registry("scorer")
DATASETS: Registry[DatasetSource] = Registry("dataset")
CUSTOM: Registry[Any] = Registry("custom_kind")
NON_REG = some_func("not_a_registry")
"""
        plugins_file = tmp_path / "plugins.py"
        plugins_file.write_text(plugins_code, encoding="utf-8")

        res = extract_registries.discover_registries(plugins_file)
        assert res == {
            "SCORERS": "scorers",
            "DATASETS": "datasets",
            "CUSTOM": "custom_kinds",
        }

    def test_discover_registries_from_plain_assignments(self, tmp_path: Path) -> None:
        plugins_code = """
JUDGES = Registry("judge")
TARGETS = Registry("targets")
"""
        plugins_file = tmp_path / "plugins.py"
        plugins_file.write_text(plugins_code, encoding="utf-8")

        res = extract_registries.discover_registries(plugins_file)
        assert res == {
            "JUDGES": "judges",
            "TARGETS": "targets",
        }

    def test_discover_registries_handles_missing_or_corrupt_files(self, tmp_path: Path) -> None:
        # Non-existent file
        assert extract_registries.discover_registries(tmp_path / "missing.py") == {}

        # Syntax error file
        corrupt = tmp_path / "corrupt.py"
        corrupt.write_text("def broken(: pass", encoding="utf-8")
        assert extract_registries.discover_registries(corrupt) == {}


class TestExtractComponents:
    """Unit tests for extracting @REGISTRY.register decorators via AST."""

    def test_extract_positional_and_keyword_decorator_names(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "scorers.py").write_text(
            """
@SCORERS.register("exact_match")
def exact_match(): pass

@SCORERS.register(name="custom_score")
def custom_score(): pass

@SCORERS.register(key="key_score")
def key_score(): pass

@DATASETS.register("csv_data")
class CsvData: pass
""",
            encoding="utf-8",
        )

        registries = {"SCORERS": "scorers", "DATASETS": "datasets"}
        found = extract_registries.extract_components(pkg, registries)

        assert found["SCORERS"] == {"exact_match", "custom_score", "key_score"}
        assert found["DATASETS"] == {"csv_data"}

    def test_extract_ignores_untracked_registries(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "other.py").write_text(
            """
@OTHER.register("untracked")
def untracked(): pass
""",
            encoding="utf-8",
        )

        found = extract_registries.extract_components(pkg, {"SCORERS": "scorers"})
        assert "OTHER" not in found
        assert found["SCORERS"] == set()

    def test_extract_all_registries_when_none_specified(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "other.py").write_text(
            """
@ANY_REGISTRY.register("item1")
def item1(): pass
""",
            encoding="utf-8",
        )

        found = extract_registries.extract_components(pkg, None)
        assert "ANY_REGISTRY" in found
        assert found["ANY_REGISTRY"] == {"item1"}

    def test_extract_handles_non_call_or_invalid_decorators(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "misc.py").write_text(
            """
@staticmethod
@SCORERS.other_method("ignored")
@SCORERS.register(123)  # non-string constant
@SCORERS.register()     # empty args
def foo(): pass
""",
            encoding="utf-8",
        )

        # Also add a broken syntax file in the dir to exercise error handling
        (pkg / "bad_syntax.py").write_text("def broken( pass\n", encoding="utf-8")

        found = extract_registries.extract_components(pkg, {"SCORERS": "scorers"})
        assert found["SCORERS"] == set()

    def test_extract_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert extract_registries.extract_components(tmp_path / "does_not_exist") == {}


class TestExtractSectionText:
    """Unit tests for matching markdown doc sections."""

    def test_extract_indented_list_section(self) -> None:
        doc = """
  scorers/
    exact_match - matches string exactly
    regex_match - checks regex pattern
  datasets/
    csv - reads CSVs
"""
        sec = extract_registries.extract_section_text(doc, "scorers")
        assert sec is not None
        assert "exact_match" in sec
        assert "regex_match" in sec
        assert "csv" not in sec

    def test_extract_markdown_table_section(self) -> None:
        doc = """
| Registry | Components |
|---|---|
| `scorers/` | exact_match, regex_match |
| `judges/` | openai, anthropic |
"""
        sec = extract_registries.extract_section_text(doc, "scorers")
        assert sec is not None
        assert "exact_match" in sec
        assert "openai" not in sec

    def test_extract_heading_section(self) -> None:
        doc = """
# Available scorers
- exact_match
- regex_match

# Next Section
- other
"""
        sec = extract_registries.extract_section_text(doc, "scorers")
        assert sec is not None
        assert "exact_match" in sec
        assert "other" not in sec

    def test_unmatched_section_returns_none(self) -> None:
        assert extract_registries.extract_section_text("Nothing relevant here", "nonexistent") is None


class TestCheckDocsDrift:
    """Integration and drift detection tests."""

    def test_detects_undocumented_components(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        plugins = src / "plugins.py"
        plugins.write_text('SCORERS: Registry[Any] = Registry("scorer")', encoding="utf-8")

        (src / "comp.py").write_text('@SCORERS.register("hidden_scorer")\ndef f(): pass', encoding="utf-8")

        readme = tmp_path / "README.md"
        readme.write_text("  scorers/\n    other_scorer", encoding="utf-8")

        problems = extract_registries.check_docs_drift(
            src_dir=src,
            plugins_path=plugins,
            doc_paths=[readme],
        )
        assert len(problems) == 1
        assert "omits registered component(s)" in problems[0]
        assert "hidden_scorer" in problems[0]

    def test_detects_empty_registry_or_missing_plugins(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        # Missing plugins file
        problems = extract_registries.check_docs_drift(
            src_dir=src,
            plugins_path=src / "missing_plugins.py",
        )
        assert len(problems) == 1
        assert "No registries discovered" in problems[0]

        # Empty registry with no @register calls
        plugins = src / "plugins.py"
        plugins.write_text('EMPTY_REG: Registry[Any] = Registry("empty")', encoding="utf-8")
        readme = tmp_path / "README.md"
        readme.write_text("  emptys/\n    something", encoding="utf-8")

        problems2 = extract_registries.check_docs_drift(
            src_dir=src,
            plugins_path=plugins,
            doc_paths=[readme],
        )
        assert any("no @EMPTY_REG.register(...) found" in p for p in problems2)

    def test_clean_documentation_has_no_drift(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        plugins = src / "plugins.py"
        plugins.write_text('SCORERS: Registry[Any] = Registry("scorer")', encoding="utf-8")

        (src / "comp.py").write_text('@SCORERS.register("valid_scorer")\ndef f(): pass', encoding="utf-8")

        readme = tmp_path / "README.md"
        readme.write_text("  scorers/\n    valid_scorer", encoding="utf-8")

        problems = extract_registries.check_docs_drift(
            src_dir=src,
            plugins_path=plugins,
            doc_paths=[readme],
        )
        assert problems == []


class TestCLIExecution:
    """Test CLI interface of extract_registries and check_readme_registries."""

    def test_cli_json_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = extract_registries.main(["--json"])
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "registries" in data
        assert "components" in data
        assert "SCORERS" in data["registries"]
        assert "exact_match" in data["components"]["SCORERS"]

    def test_cli_check_mode_on_real_repo(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = extract_registries.main(["--check", "-v"])
        assert code == 0
        captured = capsys.readouterr()
        assert "READMEs match the component registries" in captured.out

    def test_cli_check_failure_returns_exit_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        src = tmp_path / "src"
        src.mkdir()
        plugins = src / "plugins.py"
        plugins.write_text('SCORERS: Registry[Any] = Registry("scorer")', encoding="utf-8")
        (src / "comp.py").write_text('@SCORERS.register("missing_doc")\ndef f(): pass', encoding="utf-8")
        readme = tmp_path / "README.md"
        readme.write_text("  scorers/\n    other_doc", encoding="utf-8")

        code = extract_registries.main(
            [
                "--src",
                str(src),
                "--plugins",
                str(plugins),
                "--docs",
                str(readme),
                "--check",
            ]
        )
        assert code == 1
        captured = capsys.readouterr()
        assert "REGISTRY DRIFT DETECTED" in captured.out
        assert "missing_doc" in captured.out

    def test_check_readme_registries_main_wrapper(self) -> None:
        # Should complete without error
        check_readme_registries.main()

    def test_check_readme_registries_main_failure_exits(self) -> None:
        with patch("extract_registries.main", return_value=1):
            with pytest.raises(SystemExit) as exc:
                check_readme_registries.main()
            assert exc.value.code == 1
