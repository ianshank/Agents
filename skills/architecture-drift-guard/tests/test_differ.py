"""Tests for diffing actual vs declared component edges."""

from __future__ import annotations

from adguard.differ import diff_edges, format_report


def test_clean_has_no_drift():
    diff = diff_edges({("a", "b")}, {("a", "b")})
    assert not diff.has_drift
    assert diff.undocumented == []
    assert diff.unused == []


def test_undocumented_edge_is_drift():
    diff = diff_edges({("a", "b"), ("b", "a")}, {("a", "b")})
    assert diff.has_drift
    assert diff.undocumented == [("b", "a")]


def test_unused_edge_is_warning_only():
    diff = diff_edges(set(), {("a", "b")})
    assert not diff.has_drift
    assert diff.unused == [("a", "b")]


def test_results_are_sorted():
    diff = diff_edges({("z", "y"), ("a", "b")}, set())
    assert diff.undocumented == [("a", "b"), ("z", "y")]


def test_report_clean_message():
    report = format_report(diff_edges(set(), set()))
    assert "matches the manifest" in report


def test_report_lists_drift_and_warnings():
    diff = diff_edges({("b", "a")}, {("a", "b"), ("c", "d")})
    report = format_report(diff)
    assert "b -> a" in report
    assert "[warn] a -> b" in report
    assert "[warn] c -> d" in report
