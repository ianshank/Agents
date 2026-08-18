"""Unit tests for implreview.compose: create vs. append, never a silent overwrite."""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from implreview.compose import compose_review, default_reviewed_line, render_followup_section, render_new_review
from implreview.prompts import PRECEDENT_REVIEW

_GOOD_BODY = """\
## Verdict

**APPROVE.** Looks fine.

---

## Pass 1 -- mechanical fact-check (2026-08-17)

Confirmed everything.

## Pass 2 -- adversarial (2026-08-17)

Tried to break it, could not.

## Residual risk

None.

## Overall verdict

**APPROVE.**
"""

_MALFORMED_BODY = "Just some prose, no headings at all.\n"


def test_default_reviewed_line_plugin_path() -> None:
    line = default_reviewed_line("abc123", "plugin")
    assert "spec-guardian" in line
    assert "peer-reviewer" in line
    assert "abc123" in line
    assert PRECEDENT_REVIEW in line


def test_default_reviewed_line_degraded_path() -> None:
    line = default_reviewed_line("abc123", "degraded")
    assert "general-purpose" in line
    assert "ADR 0028" in line
    assert "abc123" in line


def test_render_new_review_strips_a_leading_title_from_body() -> None:
    body_with_title = "# Review: wrong-id\n\n" + _GOOD_BODY
    text = render_new_review(change_id="right-id", reviewed_line="**Reviewed:** x.", body=body_with_title)
    assert text.startswith("# Review: right-id\n")
    assert "wrong-id" not in text


def test_render_new_review_without_a_leading_title_in_body() -> None:
    text = render_new_review(change_id="right-id", reviewed_line="**Reviewed:** x.", body=_GOOD_BODY)
    assert text.startswith("# Review: right-id\n")
    assert "## Verdict" in text


def test_render_followup_section_demotes_headings_and_dates_the_section() -> None:
    section = render_followup_section(date="2026-09-01", body=_GOOD_BODY)
    assert section.startswith("\n\n---\n\n## Follow-up review -- 2026-09-01\n")
    assert "### Verdict" in section
    assert "### Pass 1" in section
    # No line in the demoted body starts at the ## (exactly two hash) level -- the section's
    # own "## Follow-up review" heading is the only ## heading, everything else moved to ###.
    top_level_headings = re.findall(r"^## .+$", section, re.MULTILINE)
    assert top_level_headings == ["## Follow-up review -- 2026-09-01"]


def test_compose_review_creates_when_absent(tmp_path: Path) -> None:
    review_path = tmp_path / "openspec" / "changes" / "demo" / "review.md"
    result = compose_review(review_path, change_id="demo", tree_sha="abc123", dispatch_path="degraded", body=_GOOD_BODY)
    assert result.mode == "created"
    assert review_path.is_file()
    assert result.validation.ok is True
    assert result.validation.verdict == "APPROVE"
    assert review_path.read_text(encoding="utf-8").startswith("# Review: demo\n")


def test_compose_review_creates_parent_directories(tmp_path: Path) -> None:
    review_path = tmp_path / "a" / "b" / "c" / "review.md"
    compose_review(review_path, change_id="demo", tree_sha="abc123", dispatch_path="degraded", body=_GOOD_BODY)
    assert review_path.is_file()


def test_compose_review_appends_when_present_and_preserves_prior_content(tmp_path: Path) -> None:
    review_path = tmp_path / "review.md"
    original = "# Review: demo\n\n**Reviewed:** first pass.\n\n" + _GOOD_BODY
    review_path.write_text(original, encoding="utf-8")

    result = compose_review(
        review_path, change_id="demo", tree_sha="def456", dispatch_path="degraded", body=_GOOD_BODY, date="2026-09-01"
    )

    assert result.mode == "appended"
    final_text = review_path.read_text(encoding="utf-8")
    assert final_text.startswith(original.rstrip("\n") + "\n")  # every prior byte preserved
    assert "## Follow-up review -- 2026-09-01" in final_text
    assert result.validation.ok is True


def test_compose_review_overwrite_replaces_prior_content(tmp_path: Path) -> None:
    review_path = tmp_path / "review.md"
    review_path.write_text("# Review: demo\n\nSTALE CONTENT THAT SHOULD BE GONE.\n", encoding="utf-8")

    result = compose_review(
        review_path, change_id="demo", tree_sha="abc123", dispatch_path="degraded", body=_GOOD_BODY, overwrite=True
    )

    assert result.mode == "overwritten"
    final_text = review_path.read_text(encoding="utf-8")
    assert "STALE CONTENT" not in final_text


def test_compose_review_default_date_is_today(tmp_path: Path) -> None:
    review_path = tmp_path / "review.md"
    review_path.write_text("# Review: demo\n\n" + _GOOD_BODY, encoding="utf-8")
    compose_review(review_path, change_id="demo", tree_sha="abc123", dispatch_path="degraded", body=_GOOD_BODY)
    today = _dt.date.today().isoformat()
    assert f"## Follow-up review -- {today}" in review_path.read_text(encoding="utf-8")


def test_compose_review_reports_invalid_structure_without_masking_it(tmp_path: Path) -> None:
    review_path = tmp_path / "review.md"
    result = compose_review(
        review_path, change_id="demo", tree_sha="abc123", dispatch_path="degraded", body=_MALFORMED_BODY
    )
    assert result.mode == "created"
    assert review_path.is_file()  # still written -- compose never silently drops output
    assert result.validation.ok is False
    assert result.validation.errors  # the caller can see exactly what is structurally wrong


def test_compose_review_custom_reviewed_line_is_used_verbatim(tmp_path: Path) -> None:
    review_path = tmp_path / "review.md"
    result = compose_review(
        review_path,
        change_id="demo",
        tree_sha="abc123",
        dispatch_path="degraded",
        body=_GOOD_BODY,
        reviewed_line="**Reviewed:** a completely custom line.",
    )
    assert "a completely custom line" in review_path.read_text(encoding="utf-8")
    assert result.mode == "created"
