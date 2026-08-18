"""Assemble the final ``review.md``, and resolve create-vs-append without ambiguity.

**Decision (documented here, not left implicit — see also ``SKILL.md`` Sec. 4):** a
``review.md`` is never silently overwritten. If it does not exist, this writes a fresh
document in the canonical shape. If it already exists, this appends a new, separately dated
``## Follow-up review — <date>`` section after every byte of the existing content, demoting
the new pass's own headings by one level so the file stays one coherent, navigable hierarchy
rather than several competing top-level documents concatenated together. This mirrors the real
pattern this repo already uses for a document that accumulates dated passes over time —
``openspec/changes/add-panel-judge/review.md``'s own separately dated "Second pass" section,
appended to the first rather than replacing it. ``overwrite=True`` exists for the rare,
deliberate case of redoing a bad file; it is never the default, and every call site that uses
it should treat it as a documented exception, not a routine option.

The substantive Verdict/Pass 1/Pass 2/Residual-risk content is never fabricated here — it is
supplied by whichever reviewer was actually dispatched (see :mod:`implreview.prompts`). This
module's job is purely mechanical: give that content the correct title, reviewed-line, and
placement, then report whether the result satisfies :mod:`implreview.validate`'s structural
contract.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .prompts import PRECEDENT_REVIEW
from .validate import ReviewValidation, validate_review_structure

if TYPE_CHECKING:
    from .detect import DispatchPath

_TITLE_LINE_RE = re.compile(r"^#\s+Review:\s*\S.*$")
_HEADING_DEMOTE_RE = re.compile(r"^##(?!#)", re.MULTILINE)

ComposeMode = Literal["created", "appended", "overwritten"]


@dataclass(frozen=True)
class ComposeResult:
    """Outcome of one :func:`compose_review` call, including a fresh structural check."""

    path: Path
    mode: ComposeMode
    validation: ReviewValidation


def _strip_leading_title(body: str) -> str:
    """Drop a leading ``# Review: ...`` line (and the blank lines after it), if present.

    The canonical title this module renders is always derived from ``change_id``, never
    trusted verbatim from dispatched output — this keeps the title byte-predictable even if a
    reviewer's own title line drifted slightly from the exact change id.
    """
    lines = body.splitlines()
    if lines and _TITLE_LINE_RE.match(lines[0]):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines)


def _demote_headings(text: str) -> str:
    """Shift every top-level (``## ``) heading down one level (``### ``).

    Used only for an appended follow-up section, so its own Verdict/Pass 1/Pass 2 headings
    nest under that section's ``## Follow-up review — <date>`` heading instead of competing
    with the original pass's top-level headings for document structure.
    """
    return _HEADING_DEMOTE_RE.sub("###", text)


def default_reviewed_line(tree_sha: str, dispatch_path: DispatchPath) -> str:
    """The standard ``**Reviewed:** ...`` opening line, naming the tree and dispatch method."""
    method = (
        "the `spec-guardian` -> `peer-reviewer` charters"
        if dispatch_path == "plugin"
        else (
            "a `general-purpose` subagent with the two-pass method inlined "
            "(claude-foundation is staged, not plugin-loaded, in this session -- ADR 0028)"
        )
    )
    return f"**Reviewed:** tree `{tree_sha}`, via {method}, following the two-pass method in `{PRECEDENT_REVIEW}`."


def render_new_review(*, change_id: str, reviewed_line: str, body: str) -> str:
    """Assemble a fresh document: canonical title + reviewed-line + the dispatched body."""
    stripped = _strip_leading_title(body).strip("\n")
    return f"# Review: {change_id}\n\n{reviewed_line}\n\n{stripped}\n"


def render_followup_section(*, date: str, body: str) -> str:
    """A dated follow-up section, ready to append after existing content."""
    stripped = _strip_leading_title(body).strip("\n")
    demoted = _demote_headings(stripped)
    return f"\n\n---\n\n## Follow-up review -- {date}\n\n{demoted}\n"


def compose_review(
    review_path: Path,
    *,
    change_id: str,
    tree_sha: str,
    dispatch_path: DispatchPath,
    body: str,
    reviewed_line: str | None = None,
    date: str | None = None,
    overwrite: bool = False,
) -> ComposeResult:
    """Write or extend *review_path* with *body*, then report its structural validity.

    ``body`` is the substantive markdown a dispatched reviewer produced (expected to already
    contain ``## Verdict`` / ``## Pass 1`` / ``## Pass 2`` per the prompts in
    :mod:`implreview.prompts`); this function supplies the title, reviewed-line, and
    create-vs-append placement around it.
    """
    resolved_date = date or _dt.date.today().isoformat()
    line = reviewed_line or default_reviewed_line(tree_sha, dispatch_path)
    exists = review_path.is_file()

    if not exists or overwrite:
        text = render_new_review(change_id=change_id, reviewed_line=line, body=body)
        mode: ComposeMode = "overwritten" if exists else "created"
    else:
        existing = review_path.read_text(encoding="utf-8")
        text = existing.rstrip("\n") + "\n" + render_followup_section(date=resolved_date, body=body)
        mode = "appended"

    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(text, encoding="utf-8", newline="\n")
    validation = validate_review_structure(text, expected_change_id=change_id)
    return ComposeResult(path=review_path, mode=mode, validation=validation)
