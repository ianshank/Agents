"""Unit tests for rubric extraction, mark computation, and sign-off verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend_validation import MARK_ABSENT, MARK_FULL, MARK_PARTIAL
from backend_validation.observables import Observable, OpOutcome
from backend_validation.registry import Predicate, SignoffBlock
from backend_validation.rubric import (
    RubricError,
    RubricRules,
    compute_mark,
    extract_machine_block,
    flat_view,
    load_rubric,
    predicate_holds,
    verify_signoff,
)

SUBTREE = Path(__file__).resolve().parents[1]


def _observable(operation: str, status: str = "ok", **extra: object) -> Observable:
    return Observable(
        probe_id="l1.x.y",
        cell_id="cell",
        backend="langfuse",
        rep_index=0,
        ts_utc="2026-07-20T00:00:00+00:00",
        outcome=OpOutcome(operation=operation, status=status, latency_ms=1.0),
        extra=dict(extra),
    )


# ------------------------------------------------------------------- extraction
def test_committed_rubric_parses_and_ships_unsigned() -> None:
    rules = load_rubric(SUBTREE / "RUBRIC.md")
    assert rules.rubric_version == 1
    assert rules.signoff.signed_off is False
    assert rules.halt.unexpected_control_pass is True
    assert rules.partial_rule_for("rag.metrics").min_expected_fraction == 0.5
    assert rules.partial_rule_for("anything.else").some_expected_hold is True


def test_extract_requires_marker_and_exactly_one_fence() -> None:
    with pytest.raises(RubricError, match="no <!-- rubric:machine --> marker"):
        extract_machine_block("just prose\n")
    two = "<!-- rubric:machine -->\n```yaml\na: 1\n```\n```yaml\nb: 2\n```\n"
    with pytest.raises(RubricError, match="exactly ONE"):
        extract_machine_block(two)


def test_load_rubric_error_paths(tmp_path: Path) -> None:
    with pytest.raises(RubricError, match="cannot read"):
        load_rubric(tmp_path / "missing.md")
    bad_yaml = tmp_path / "RUBRIC.md"
    bad_yaml.write_text("<!-- rubric:machine -->\n```yaml\n[unclosed\n```\n", encoding="utf-8")
    with pytest.raises(RubricError, match="not valid YAML"):
        load_rubric(bad_yaml)
    wrong_shape = tmp_path / "RUBRIC2.md"
    wrong_shape.write_text("<!-- rubric:machine -->\n```yaml\nrubric_version: 1\n```\n", encoding="utf-8")
    with pytest.raises(RubricError, match="failed validation"):
        load_rubric(wrong_shape)


# ------------------------------------------------------------------- evaluation
def test_flat_view_merges_outcome_fields_and_extras() -> None:
    view = flat_view(_observable("create_trace", trace_visible=True))
    assert view["status"] == "ok"
    assert view["trace_visible"] is True
    assert view["retries"] == 0


def test_predicate_holds_matches_operation_and_field() -> None:
    observables = [_observable("create_trace"), _observable("fetch_trace", trace_visible=True)]
    assert predicate_holds(Predicate(operation="fetch_trace", field="trace_visible", equals=True), observables)
    assert predicate_holds(Predicate(operation="create_trace", field="status", equals="ok"), observables)
    assert not predicate_holds(Predicate(operation="create_trace", field="status", equals="error"), observables)
    assert not predicate_holds(Predicate(operation="unknown_op", field="status", equals="ok"), observables)


@pytest.fixture(name="rules")
def _rules() -> RubricRules:
    return load_rubric(SUBTREE / "RUBRIC.md")


def test_compute_mark_default_mapping(rules: RubricRules) -> None:
    assert compute_mark(rules, "tracing.observability", [True, True, True]) == MARK_FULL
    assert compute_mark(rules, "tracing.observability", [True, False, False]) == MARK_PARTIAL
    assert compute_mark(rules, "tracing.observability", [False, False]) == MARK_ABSENT


def test_compute_mark_override_fraction(rules: RubricRules) -> None:
    # rag.metrics override: >= 0.5 of expected observables held -> partial, below -> absent.
    assert compute_mark(rules, "rag.metrics", [True, True, False, False]) == MARK_PARTIAL
    assert compute_mark(rules, "rag.metrics", [True, False, False, False, False]) == MARK_ABSENT
    assert compute_mark(rules, "rag.metrics", [True, True, True]) == MARK_FULL


def test_compute_mark_requires_outcomes(rules: RubricRules) -> None:
    with pytest.raises(RubricError, match="no predicate outcomes"):
        compute_mark(rules, "x", [])


# --------------------------------------------------------------------- sign-off
def _signed_root(tmp_path: Path) -> Path:
    (tmp_path / "PROBES.yaml").write_text("probes: signed\n", encoding="utf-8")
    (tmp_path / "RUBRIC.md").write_text("rubric: signed\n", encoding="utf-8")
    lines = []
    for name in ("PROBES.yaml", "RUBRIC.md"):
        digest = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        lines.append(f"sha256 {digest}  {name}")
    lines.append("signed_by: reviewer")
    (tmp_path / "SIGNOFF").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _signed_rules(rules: RubricRules, signed: bool) -> RubricRules:
    return rules.model_copy(update={"signoff": SignoffBlock(signed_off=signed, signed_by="reviewer")})


def test_verify_signoff_happy_path(tmp_path: Path, rules: RubricRules) -> None:
    root = _signed_root(tmp_path)
    status = verify_signoff(root, SignoffBlock(signed_off=True, signed_by="reviewer"), _signed_rules(rules, True))
    assert status.ok and status.reasons == ()


def test_verify_signoff_unsigned_flags(tmp_path: Path, rules: RubricRules) -> None:
    root = _signed_root(tmp_path)
    status = verify_signoff(root, SignoffBlock(signed_off=False), _signed_rules(rules, False))
    assert not status.ok
    assert any("PROBES.yaml signoff" in reason for reason in status.reasons)
    assert any("RUBRIC.md machine-block signoff" in reason for reason in status.reasons)


def test_verify_signoff_missing_file_short_circuits(tmp_path: Path, rules: RubricRules) -> None:
    (tmp_path / "PROBES.yaml").write_text("x\n", encoding="utf-8")
    (tmp_path / "RUBRIC.md").write_text("y\n", encoding="utf-8")
    status = verify_signoff(tmp_path, SignoffBlock(signed_off=True), _signed_rules(rules, True))
    assert not status.ok
    assert any("SIGNOFF file is missing" in reason for reason in status.reasons)


def test_verify_signoff_detects_post_signing_drift(tmp_path: Path, rules: RubricRules) -> None:
    root = _signed_root(tmp_path)
    (root / "PROBES.yaml").write_text("probes: TAMPERED\n", encoding="utf-8")
    status = verify_signoff(root, SignoffBlock(signed_off=True), _signed_rules(rules, True))
    assert not status.ok
    assert any("does not match the file" in reason for reason in status.reasons)


def test_verify_signoff_rejects_junk_and_missing_lines(tmp_path: Path, rules: RubricRules) -> None:
    root = _signed_root(tmp_path)
    (root / "SIGNOFF").write_text("sha256 deadbeef  PROBES.yaml\nwhat is this line\n", encoding="utf-8")
    status = verify_signoff(root, SignoffBlock(signed_off=True), _signed_rules(rules, True))
    assert not status.ok
    assert any("unrecognized line" in reason for reason in status.reasons)
    assert any("missing a sha256 line for RUBRIC.md" in reason for reason in status.reasons)
    assert any("signed_by" in reason for reason in status.reasons)
