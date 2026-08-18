"""Structural validation of a produced ``review.md``.

The required shape is calibrated against two *real*, already-merged artifacts in this repo —
``openspec/changes/archive/harden-quality-gate-integrity/review.md`` and
``openspec/changes/archive/test-skill-validator-library/review.md`` — not against an idealized
template. That matters concretely: an earlier draft of this checker required a distinct,
file-final ``## Overall verdict`` heading, which the second of those two real, accepted
reviews does not have (it ends on ``## Residual risk / follow-ups``, having already stated its
verdict once, up front, under ``## Verdict``). The house convention both real files agree on is
**verdict-first** — see ``spec-guardian``'s and ``peer-reviewer``'s own charters, Rule 5/6:
"Report verdict-first" — not verdict-last, so this validator checks for that instead of a
shape only one of the two precedents actually has.

Similarly, "separately dated" (both charters, and both real reviews) means each pass carries
its *own* date annotation in its own heading line — it does not require the two dates to
differ. Both real reviews date Pass 1 and Pass 2 the same calendar day; requiring two distinct
dates would fail both of them.

What is (and is not) checked is deliberately narrow, in the same spirit as
``docs/SKILL_VALIDATION_TEMPLATE.md``'s own honesty note: this proves the document has the
right *shape*, never that its findings are correct. Substance review is exactly the job the
skill delegates to a dispatched reviewer (or documents as unverifiable in the degraded path);
no script can grade that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: A canonical verdict token. Checked longest-first so "APPROVE WITH FOLLOW-UPS" is never
#: mis-detected as the bare "APPROVE" prefix it contains.
VERDICT_TOKENS: tuple[str, ...] = ("APPROVE WITH FOLLOW-UPS", "BLOCK", "APPROVE")

_TITLE_RE = re.compile(r"^#\s+Review:\s*(\S.*?)\s*$", re.MULTILINE)
_VERDICT_HEADING_RE = re.compile(r"^##\s+(?:Overall\s+)?Verdict\s*$", re.MULTILINE)
_PASS1_HEADING_RE = re.compile(r"^##\s+Pass\s+1\b.*$", re.MULTILINE)
_PASS2_HEADING_RE = re.compile(r"^##\s+Pass\s+2\b.*$", re.MULTILINE)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FOLLOWUP_HEADING_RE = re.compile(r"^##\s+Follow-up review\b.*$", re.MULTILINE)
_ANY_H2_RE = re.compile(r"^##\s", re.MULTILINE)


@dataclass(frozen=True)
class ReviewValidation:
    """Result of checking one ``review.md`` document's structure."""

    ok: bool
    errors: tuple[str, ...]
    verdict: str | None
    title_change_id: str | None
    pass1_dated: bool
    pass2_dated: bool
    followup_sections: int


def _find_verdict_token(text: str, heading_match: re.Match[str]) -> str | None:
    """Search only the "## Verdict" section's own body -- up to the *next* ``## `` heading.

    Bounding by the next heading (rather than a fixed character count) is what a section
    actually is; a fixed-size window can "see through" a short section into a later,
    unrelated one (e.g. a trailing "## Overall verdict") on a short document and report a
    false match.
    """
    body = text[heading_match.end() :]
    next_heading = _ANY_H2_RE.search(body)
    window = body[: next_heading.start()] if next_heading else body
    return next((tok for tok in VERDICT_TOKENS if tok in window), None)


def _check_title(text: str, expected_change_id: str | None, errors: list[str]) -> str | None:
    match = _TITLE_RE.search(text)
    if not match:
        errors.append("missing a '# Review: <change-id>' title line")
        return None
    title_id = match.group(1).strip()
    if expected_change_id is not None and title_id != expected_change_id:
        errors.append(f"title names {title_id!r}, expected {expected_change_id!r}")
    return title_id


def _check_verdict(text: str, heading_match: re.Match[str] | None, errors: list[str]) -> str | None:
    if heading_match is None:
        errors.append("missing a '## Verdict' (or '## Overall Verdict') heading")
        return None
    token = _find_verdict_token(text, heading_match)
    if token is None:
        errors.append(
            "the '## Verdict' section does not state one of the canonical verdict tokens "
            f"({', '.join(VERDICT_TOKENS)}) within its opening paragraph"
        )
    return token


def _check_pass_ordering(text: str, verdict_pos: int | None, errors: list[str]) -> tuple[bool, bool]:
    pass1 = _PASS1_HEADING_RE.search(text)
    pass2 = _PASS2_HEADING_RE.search(text)
    if pass1 is None:
        errors.append("missing a '## Pass 1 ...' (mechanical fact-check) heading")
    if pass2 is None:
        errors.append("missing a '## Pass 2 ...' (adversarial) heading")
    if pass1 and pass2 and pass1.start() > pass2.start():
        errors.append("'## Pass 1' must appear before '## Pass 2'")
    if verdict_pos is not None and pass1 and verdict_pos > pass1.start():
        errors.append("'## Verdict' must appear before '## Pass 1' (verdict-first reporting)")
    pass1_dated = bool(pass1 and _DATE_RE.search(pass1.group(0)))
    pass2_dated = bool(pass2 and _DATE_RE.search(pass2.group(0)))
    if pass1 and not pass1_dated:
        errors.append("'## Pass 1' heading has no YYYY-MM-DD date")
    if pass2 and not pass2_dated:
        errors.append("'## Pass 2' heading has no YYYY-MM-DD date")
    return pass1_dated, pass2_dated


def validate_review_structure(text: str, *, expected_change_id: str | None = None) -> ReviewValidation:
    """Check *text* against the shape shared by this repo's real implementation reviews."""
    errors: list[str] = []
    title_id = _check_title(text, expected_change_id, errors)
    verdict_match = _VERDICT_HEADING_RE.search(text)
    verdict = _check_verdict(text, verdict_match, errors)
    pass1_dated, pass2_dated = _check_pass_ordering(text, verdict_match.start() if verdict_match else None, errors)
    followups = len(_FOLLOWUP_HEADING_RE.findall(text))
    return ReviewValidation(
        ok=not errors,
        errors=tuple(errors),
        verdict=verdict,
        title_change_id=title_id,
        pass1_dated=pass1_dated,
        pass2_dated=pass2_dated,
        followup_sections=followups,
    )


def validate_review_file(path: Path, *, expected_change_id: str | None = None) -> ReviewValidation:
    """:func:`validate_review_structure` over a file on disk (missing file is one error)."""
    if not path.is_file():
        return ReviewValidation(
            ok=False,
            errors=(f"{path} does not exist",),
            verdict=None,
            title_change_id=None,
            pass1_dated=False,
            pass2_dated=False,
            followup_sections=0,
        )
    return validate_review_structure(path.read_text(encoding="utf-8"), expected_change_id=expected_change_id)
