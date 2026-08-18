"""Unit tests for implreview.validate.

The final three tests run the validator against the *real*, already-merged review.md files in
this repo -- the two genuine implementation reviews this skill's output is meant to match, and
one deliberate non-match (a pre-implementation plan review, a different artifact this skill
does not produce) documenting the boundary honestly rather than asserting only the happy path.
"""

from __future__ import annotations

from pathlib import Path

from implreview.validate import validate_review_file, validate_review_structure

REPO_ROOT = Path(__file__).resolve().parents[3]

_MINIMAL_VALID = """\
# Review: demo-change

**Reviewed:** tree `abc123`, via a general-purpose subagent.

## Verdict

**APPROVE.** Everything checked out.

---

## Pass 1 -- mechanical fact-check (2026-08-17)

| # | Claim | Verdict |
|---|---|---|
| 1 | thing works | CONFIRMED |

## Pass 2 -- adversarial (2026-08-17)

Tried to break it. Nothing broke.

## Residual risk

None found.

## Overall verdict

**APPROVE.**
"""


def test_minimal_valid_document_passes() -> None:
    result = validate_review_structure(_MINIMAL_VALID, expected_change_id="demo-change")
    assert result.ok is True
    assert result.errors == ()
    assert result.verdict == "APPROVE"
    assert result.title_change_id == "demo-change"
    assert result.pass1_dated is True
    assert result.pass2_dated is True


def test_missing_title_is_an_error() -> None:
    text = _MINIMAL_VALID.replace("# Review: demo-change\n\n", "")
    result = validate_review_structure(text)
    assert result.ok is False
    assert any("title" in e for e in result.errors)


def test_title_mismatch_is_an_error() -> None:
    result = validate_review_structure(_MINIMAL_VALID, expected_change_id="some-other-change")
    assert result.ok is False
    assert any("some-other-change" in e for e in result.errors)


def test_missing_verdict_heading_is_an_error() -> None:
    text = _MINIMAL_VALID.replace("## Verdict\n\n**APPROVE.** Everything checked out.\n\n", "")
    result = validate_review_structure(text)
    assert result.ok is False
    assert result.verdict is None
    assert any("Verdict" in e for e in result.errors)


def test_verdict_heading_without_a_canonical_token_is_an_error() -> None:
    text = _MINIMAL_VALID.replace("**APPROVE.** Everything checked out.", "It's complicated.")
    result = validate_review_structure(text)
    assert result.ok is False
    assert result.verdict is None
    assert any("canonical verdict" in e for e in result.errors)


def test_approve_with_follow_ups_is_not_confused_with_bare_approve() -> None:
    text = _MINIMAL_VALID.replace("**APPROVE.**", "**APPROVE WITH FOLLOW-UPS.**")
    result = validate_review_structure(text)
    assert result.verdict == "APPROVE WITH FOLLOW-UPS"


def test_block_verdict_is_recognized() -> None:
    text = _MINIMAL_VALID.replace("**APPROVE.**", "**BLOCK.**")
    result = validate_review_structure(text)
    assert result.verdict == "BLOCK"


def test_missing_pass_headings_are_errors() -> None:
    text = _MINIMAL_VALID.split("## Pass 1")[0]
    result = validate_review_structure(text)
    assert result.ok is False
    assert any("Pass 1" in e for e in result.errors)
    assert any("Pass 2" in e for e in result.errors)


def test_pass_headings_out_of_order_is_an_error() -> None:
    lines = _MINIMAL_VALID.splitlines()
    p1_idx = next(i for i, ln in enumerate(lines) if ln.startswith("## Pass 1"))
    p2_idx = next(i for i, ln in enumerate(lines) if ln.startswith("## Pass 2"))
    lines[p1_idx], lines[p2_idx] = lines[p2_idx], lines[p1_idx]
    result = validate_review_structure("\n".join(lines))
    assert result.ok is False
    assert any("before" in e for e in result.errors)


def test_verdict_after_pass1_is_an_error() -> None:
    # Move the Verdict section to the very end -- violates verdict-first reporting.
    verdict_block = "## Verdict\n\n**APPROVE.** Everything checked out.\n\n---\n\n"
    text = _MINIMAL_VALID.replace(verdict_block, "") + "\n" + verdict_block
    result = validate_review_structure(text)
    assert result.ok is False
    assert any("verdict-first" in e for e in result.errors)


def test_pass_heading_without_a_date_is_an_error() -> None:
    text = _MINIMAL_VALID.replace(
        "## Pass 1 -- mechanical fact-check (2026-08-17)", "## Pass 1 -- mechanical fact-check"
    )
    result = validate_review_structure(text)
    assert result.ok is False
    assert any("Pass 1" in e and "date" in e for e in result.errors)
    assert result.pass1_dated is False
    assert result.pass2_dated is True  # Pass 2's own date is untouched by this mutation


def test_pass2_heading_without_a_date_is_an_error() -> None:
    text = _MINIMAL_VALID.replace("## Pass 2 -- adversarial (2026-08-17)", "## Pass 2 -- adversarial")
    result = validate_review_structure(text)
    assert result.ok is False
    assert any("Pass 2" in e and "date" in e for e in result.errors)
    assert result.pass1_dated is True
    assert result.pass2_dated is False


def test_same_calendar_date_for_both_passes_is_fine() -> None:
    # "Separately dated" means each heading carries its own date label, not that the two
    # dates must differ -- both real precedent reviews date same-day passes this way.
    result = validate_review_structure(_MINIMAL_VALID)
    assert result.pass1_dated is True
    assert result.pass2_dated is True
    assert result.ok is True


def test_followup_sections_are_counted() -> None:
    text = _MINIMAL_VALID + "\n\n---\n\n## Follow-up review -- 2026-09-01\n\nStill fine.\n"
    result = validate_review_structure(text)
    assert result.followup_sections == 1
    assert result.ok is True  # the original required sections are untouched


def test_validate_review_file_missing_file_is_one_error(tmp_path: Path) -> None:
    result = validate_review_file(tmp_path / "nope.md")
    assert result.ok is False
    assert len(result.errors) == 1
    assert "does not exist" in result.errors[0]


def test_validate_review_file_reads_a_real_file(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    path.write_text(_MINIMAL_VALID, encoding="utf-8")
    result = validate_review_file(path, expected_change_id="demo-change")
    assert result.ok is True


# --- against the real, already-merged review.md files in this repo -------------------------


def test_real_harden_quality_gate_integrity_review_is_structurally_valid() -> None:
    path = REPO_ROOT / "openspec" / "changes" / "harden-quality-gate-integrity" / "review.md"
    result = validate_review_file(path, expected_change_id="harden-quality-gate-integrity")
    assert result.ok is True, result.errors
    assert result.verdict == "APPROVE WITH FOLLOW-UPS"


def test_real_test_skill_validator_library_review_is_structurally_valid() -> None:
    # This is the file that does NOT have a distinct final "## Overall verdict" heading (it
    # ends on "## Residual risk / follow-ups") -- the reason this validator checks
    # verdict-first, not verdict-last. If this regresses to requiring a terminal heading, this
    # real, accepted, in-repo review would incorrectly fail.
    path = REPO_ROOT / "openspec" / "changes" / "test-skill-validator-library" / "review.md"
    result = validate_review_file(path, expected_change_id="test-skill-validator-library")
    assert result.ok is True, result.errors
    assert result.verdict == "APPROVE WITH FOLLOW-UPS"


def test_real_add_panel_judge_review_is_a_different_genre_and_correctly_does_not_validate() -> None:
    # add-panel-judge/review.md is a *pre-implementation plan* review (openspec-peer-review's
    # output shape -- "Corrections applied" / "Attacks that died", no APPROVE/BLOCK verdict
    # vocabulary), not an implementation review. This skill explicitly does not produce or
    # claim to validate that shape (see SKILL.md's "what NOT to do" / the distinction from
    # openspec-peer-review) -- asserted here so the boundary is documented, not assumed.
    path = REPO_ROOT / "openspec" / "changes" / "add-panel-judge" / "review.md"
    result = validate_review_file(path, expected_change_id="add-panel-judge")
    assert result.ok is False
    assert result.verdict is None
