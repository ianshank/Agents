"""Unit tests for the drift_check runner helpers."""
from __future__ import annotations

import importlib
import os
import sys

drift_check = importlib.import_module("drift_check")


def test_prepend_sys_path_preserves_manifest_order():
    """First sys_path entry must end up first (highest precedence) on sys.path."""
    saved = list(sys.path)
    a, b = "adguard_test_aa", "adguard_test_bb"
    base = "/unused"
    expected_a = os.path.abspath(os.path.join(base, a))
    expected_b = os.path.abspath(os.path.join(base, b))
    try:
        drift_check._prepend_sys_path([a, b], base_dir=base)
        assert expected_a in sys.path and expected_b in sys.path
        assert sys.path.index(expected_a) < sys.path.index(expected_b)
    finally:
        sys.path[:] = saved


def test_prepend_sys_path_resolves_relative_against_base_dir():
    saved = list(sys.path)
    base = "/repo/proj"
    expected = os.path.abspath(os.path.join(base, "pkgs"))
    try:
        drift_check._prepend_sys_path(["pkgs"], base_dir=base)
        assert expected in sys.path
    finally:
        sys.path[:] = saved

