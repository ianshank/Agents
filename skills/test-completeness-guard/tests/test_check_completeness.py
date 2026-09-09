"""Unit tests for the public-surface mention census."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from check_completeness import (
    CompletenessUsageError,
    evaluate,
    hit_rate,
    load_baseline,
    main,
    mentioned_names,
)


def _baseline(path: Path, names: list[str]) -> Path:
    path.write_text(json.dumps({"packages": ["p"], "surface": {"p": names}}), encoding="utf-8")
    return path


def test_complete_fixture_meets_a_full_floor(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path / "baseline.json", ["Foo", "Bar"])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("def test_foo():\n    Foo = Bar = 1\n", encoding="utf-8")
    report = evaluate(baseline=baseline, tests=tests, min_hit_rate=1.0)
    assert report.passed
    assert report.exported == 2
    assert report.mentioned == 2
    assert report.missing == ()


def test_incomplete_fixture_fails_a_positive_floor(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path / "baseline.json", ["Foo", "Bar"])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("def test_foo():\n    Foo\n", encoding="utf-8")
    report = evaluate(baseline=baseline, tests=tests, min_hit_rate=1.0)
    assert not report.passed
    assert report.missing == ("Bar",)


def test_empty_baseline_fails_closed(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path / "baseline.json", [])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("def test_foo():\n    pass\n", encoding="utf-8")
    report = evaluate(baseline=baseline, tests=tests, min_hit_rate=0.0)
    assert not report.passed
    assert report.exported == 0


def test_missing_baseline_is_a_usage_error(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    with pytest.raises(CompletenessUsageError):
        load_baseline(tmp_path / "absent.json")
    assert main(["--baseline", str(tmp_path / "absent.json"), "--tests", str(tests)]) == 2


def test_missing_tests_dir_is_a_usage_error(tmp_path: Path) -> None:
    baseline = _baseline(tmp_path / "baseline.json", ["Foo"])
    assert main(["--baseline", str(baseline), "--tests", str(tmp_path / "nope")]) == 2


def test_json_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _baseline(tmp_path / "baseline.json", ["Foo"])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("Foo\n", encoding="utf-8")
    out = tmp_path / "report.json"
    assert main(["--baseline", str(baseline), "--tests", str(tests), "--format", "json", "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["exported"] == 1
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["passed"] is True


def test_hit_rate_is_zero_on_an_empty_export() -> None:
    assert hit_rate(0, 0) == 0.0
    assert hit_rate(1, 2) == 0.5


def test_mentioned_names_uses_word_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "test_x.py"
    path.write_text("Food\n", encoding="utf-8")
    assert mentioned_names([path], frozenset({"Foo"})) == frozenset()
    path.write_text("Foo\n", encoding="utf-8")
    assert mentioned_names([path], frozenset({"Foo"})) == frozenset({"Foo"})


def test_components_baseline_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"components": {"agents": ["explorer"]}}), encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("explorer\n", encoding="utf-8")
    report = evaluate(baseline=path, tests=tests, min_hit_rate=1.0)
    assert report.passed


def test_text_cli_fail_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline = _baseline(tmp_path / "baseline.json", ["Foo"])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("pass\n", encoding="utf-8")
    assert main(["--baseline", str(baseline), "--tests", str(tests), "--min-hit-rate", "1"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_baseline_that_is_not_an_object_is_a_usage_error(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(CompletenessUsageError):
        load_baseline(path)
