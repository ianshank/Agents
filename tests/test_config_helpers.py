#!/usr/bin/env python3
"""Tests for scripts/_config.py — shared changed-file + strict YAML-loader helpers."""

from __future__ import annotations

from pathlib import Path

import _config
import pytest
from _config import (
    ConfigError,
    load_yaml_mapping,
    read_nul_delimited,
    require_exact_keys,
    require_major,
    resolve_explicit_files,
)


# --- read_nul_delimited -----------------------------------------------------
def test_read_nul_delimited(tmp_path: Path):
    p = tmp_path / "f.z"
    p.write_bytes(b"a.py\x00dir/b.py\x00\x00")  # trailing empties dropped
    assert read_nul_delimited(str(p)) == ["a.py", "dir/b.py"]


def test_read_nul_delimited_non_utf8_does_not_crash(tmp_path: Path):
    # git diff -z is a byte stream; a non-UTF-8 path must not raise UnicodeDecodeError.
    p = tmp_path / "f.z"
    p.write_bytes(b"ok.py\x00bad\xff\xfe.py\x00")
    out = read_nul_delimited(str(p))
    assert out[0] == "ok.py"
    assert len(out) == 2  # the undecodable path survives via surrogateescape


def test_read_nul_delimited_missing_file_is_config_error(tmp_path: Path):
    with pytest.raises(ConfigError):
        read_nul_delimited(str(tmp_path / "nope.z"))


# --- resolve_explicit_files -------------------------------------------------
def test_resolve_explicit_files_from_list():
    assert resolve_explicit_files(["a.py", "  ", "b.py"], None) == ["a.py", "b.py"]


def test_resolve_explicit_files_from_file(tmp_path: Path):
    p = tmp_path / "f.z"
    p.write_bytes(b"x.py\x00")
    assert resolve_explicit_files(None, str(p)) == ["x.py"]


def test_resolve_explicit_files_none_when_neither():
    assert resolve_explicit_files(None, None) is None
    assert resolve_explicit_files([], None) is None  # empty list is not a source


# --- load_yaml_mapping ------------------------------------------------------
def test_load_yaml_mapping_ok(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("a: 1\nb: 2\n", encoding="utf-8")
    assert load_yaml_mapping(str(p)) == {"a": 1, "b": 2}


@pytest.mark.parametrize("content", ["- just\n- a list\n", "42\n", "just a string\n"])
def test_load_yaml_mapping_non_mapping_is_error(tmp_path: Path, content: str):
    p = tmp_path / "c.yaml"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml_mapping(str(p))


def test_load_yaml_mapping_bad_yaml_is_error(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml_mapping(str(p))


def test_load_yaml_mapping_missing_is_error(tmp_path: Path):
    with pytest.raises(ConfigError):
        load_yaml_mapping(str(tmp_path / "nope.yaml"))


# --- require_major / require_exact_keys -------------------------------------
def test_require_major_ok():
    require_major("1.2.3", "x")  # no raise
    require_major("1", "x")


def test_require_major_wrong_major():
    with pytest.raises(ConfigError):
        require_major("2.0.0", "x")


def test_require_exact_keys_ok():
    require_exact_keys({"a": 1, "b": 2}, {"a", "b"}, "cfg")  # no raise


@pytest.mark.parametrize("doc", [{"a": 1}, {"a": 1, "b": 2, "c": 3}, {}])
def test_require_exact_keys_mismatch(doc: dict):
    with pytest.raises(ConfigError):
        require_exact_keys(doc, {"a", "b"}, "cfg")


def test_supported_schema_major_constant():
    assert _config.SUPPORTED_SCHEMA_MAJOR == "1"
