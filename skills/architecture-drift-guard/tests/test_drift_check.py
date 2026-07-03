"""Unit tests for the drift_check runner helpers."""

from __future__ import annotations

import importlib
import sys

drift_check = importlib.import_module("drift_check")


def test_prepend_sys_path_preserves_manifest_order():
    """First sys_path entry must end up first (highest precedence) on sys.path."""
    saved = list(sys.path)
    a, b = "/adguard_test_aa", "/adguard_test_bb"
    try:
        drift_check._prepend_sys_path([a, b], base_dir="/unused")
        assert a in sys.path and b in sys.path
        assert sys.path.index(a) < sys.path.index(b)
    finally:
        sys.path[:] = saved


def test_prepend_sys_path_resolves_relative_against_base_dir():
    saved = list(sys.path)
    try:
        drift_check._prepend_sys_path(["pkgs"], base_dir="/repo/proj")
        assert "/repo/proj/pkgs" in sys.path
    finally:
        sys.path[:] = saved
