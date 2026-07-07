"""Tests for the shared atomic text-writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.atomic_io import atomic_write_text


def test_writes_content(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(str(target), "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_no_tmp_left_after_success(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "x")
    assert not (tmp_path / "out.txt.tmp").exists()


def test_failure_cleans_up_tmp_and_reraises(tmp_path: Path, monkeypatch, caplog) -> None:
    target = tmp_path / "out.txt"

    def boom(src: object, dst: object) -> None:
        raise OSError("replace failed")

    # Fail at the os.replace step, after the tmp file was written.
    monkeypatch.setattr("agent_core.atomic_io.os.replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "data")
    assert not (tmp_path / "out.txt.tmp").exists()  # tmp cleaned up
    assert not target.exists()  # original never created
    assert "atomic write to" in caplog.text
