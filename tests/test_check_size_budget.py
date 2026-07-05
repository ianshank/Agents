#!/usr/bin/env python3
"""Tests for the source-file size-budget gate (``scripts/check_size_budget.py``)."""

from __future__ import annotations

import json
from pathlib import Path

import check_size_budget as sb
import pytest


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _lines(n: int) -> str:
    """A syntactically valid module of exactly *n* lines."""
    return "".join(f"x{i} = {i}\n" for i in range(n))


# ---------------------------------------------------------------------------
# scan_file: file-length hard gate
# ---------------------------------------------------------------------------


def test_file_over_limit_is_hard_finding(tmp_path: Path) -> None:
    path = _write(tmp_path, "big.py", _lines(sb.MAX_FILE_LINES + 1))
    findings = sb.scan_file(path, tmp_path)
    assert [f for f in findings if f.kind == "file_lines" and f.hard] != []
    assert findings[0].value == sb.MAX_FILE_LINES + 1


def test_file_at_limit_is_clean(tmp_path: Path) -> None:
    path = _write(tmp_path, "ok.py", _lines(sb.MAX_FILE_LINES))
    assert sb.scan_file(path, tmp_path) == []


# ---------------------------------------------------------------------------
# scan_file: function-length and public-method warnings (non-blocking)
# ---------------------------------------------------------------------------


def test_long_function_is_soft_warning(tmp_path: Path) -> None:
    body = "\n".join(f"    a{i} = {i}" for i in range(sb.MAX_FUNCTION_LINES + 2))
    path = _write(tmp_path, "fn.py", f"def big():\n{body}\n")
    findings = sb.scan_file(path, tmp_path)
    fn = [f for f in findings if f.kind == "function_lines"]
    assert fn and fn[0].name == "big"
    assert all(not f.hard for f in fn)


def test_class_over_public_method_budget_warns(tmp_path: Path) -> None:
    methods = "\n".join(f"    def m{i}(self): ..." for i in range(sb.MAX_PUBLIC_METHODS + 1))
    path = _write(tmp_path, "cls.py", f"class Big:\n{methods}\n")
    findings = sb.scan_file(path, tmp_path)
    mc = [f for f in findings if f.kind == "public_methods"]
    assert mc and mc[0].value == sb.MAX_PUBLIC_METHODS + 1
    assert not mc[0].hard


def test_private_methods_do_not_count(tmp_path: Path) -> None:
    methods = "\n".join(f"    def _p{i}(self): ..." for i in range(sb.MAX_PUBLIC_METHODS + 5))
    path = _write(tmp_path, "cls.py", f"class C:\n{methods}\n")
    assert [f for f in sb.scan_file(path, tmp_path) if f.kind == "public_methods"] == []


def test_unparseable_file_is_skipped_not_crashed(tmp_path: Path) -> None:
    path = _write(tmp_path, "broken.py", "def (:\n")  # syntax error
    # No exception; file-length still measured, symbol checks skipped.
    assert sb.scan_file(path, tmp_path) == []


# ---------------------------------------------------------------------------
# exclusion + discovery
# ---------------------------------------------------------------------------


def test_excluded_dirs_are_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/mod.py", "x = 1\n")
    _write(tmp_path, "pkg/tests/test_mod.py", "y = 2\n")
    _write(tmp_path, "pkg/__pycache__/mod.py", "z = 3\n")
    files = sb.iter_source_files([tmp_path], tmp_path)
    names = {p.name for p in files}
    assert names == {"mod.py"}


def test_iter_source_files_is_sorted_and_deduped(tmp_path: Path) -> None:
    _write(tmp_path, "b.py", "x = 1\n")
    _write(tmp_path, "a.py", "x = 1\n")
    # Overlapping roots must not double-count a file.
    files = sb.iter_source_files([tmp_path, tmp_path], tmp_path)
    assert [p.name for p in files] == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# scan(): ordering (hard findings first)
# ---------------------------------------------------------------------------


def test_scan_orders_hard_findings_first(tmp_path: Path) -> None:
    _write(tmp_path, "big.py", _lines(sb.MAX_FILE_LINES + 1))
    body = "\n".join(f"    a{i} = {i}" for i in range(sb.MAX_FUNCTION_LINES + 2))
    _write(tmp_path, "fn.py", f"def big():\n{body}\n")
    findings = sb.scan([tmp_path], repo_root=tmp_path)
    assert findings[0].hard is True
    assert any(not f.hard for f in findings)


# ---------------------------------------------------------------------------
# main(): exit codes and reporting
# ---------------------------------------------------------------------------


def test_main_exit_zero_when_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    _write(tmp_path, "ok.py", "x = 1\n")
    monkeypatch.setattr(sb, "_repo_root", lambda: tmp_path)
    rc = sb.main(["--root", str(tmp_path)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_main_exit_one_on_hard_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    _write(tmp_path, "big.py", _lines(sb.MAX_FILE_LINES + 10))
    monkeypatch.setattr(sb, "_repo_root", lambda: tmp_path)
    rc = sb.main(["--root", str(tmp_path)])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    _write(tmp_path, "big.py", _lines(sb.MAX_FILE_LINES + 3))
    monkeypatch.setattr(sb, "_repo_root", lambda: tmp_path)
    rc = sb.main(["--root", str(tmp_path), "--json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["kind"] == "file_lines"
    assert payload[0]["hard"] is True


def test_main_warnings_do_not_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    body = "\n".join(f"    a{i} = {i}" for i in range(sb.MAX_FUNCTION_LINES + 2))
    _write(tmp_path, "fn.py", f"def big():\n{body}\n")
    monkeypatch.setattr(sb, "_repo_root", lambda: tmp_path)
    rc = sb.main(["--root", str(tmp_path)])
    assert rc == 0
    assert "[warn]" in capsys.readouterr().out


def test_default_root_scans_whole_repo(monkeypatch, tmp_path: Path) -> None:
    _write(tmp_path, "mod.py", "x = 1\n")
    monkeypatch.setattr(sb, "_repo_root", lambda: tmp_path)
    # No --root: falls back to _repo_root() for both scan base and roots.
    assert sb.main([]) == 0


# ---------------------------------------------------------------------------
# the real repository must satisfy the hard gate
# ---------------------------------------------------------------------------


def test_repository_has_no_oversize_source_file() -> None:
    """Dogfood: this repo's own source tree must pass the hard file-length gate."""
    hard = [f for f in sb.scan() if f.hard]
    assert hard == [], f"oversize files: {[(f.path, f.value) for f in hard]}"
