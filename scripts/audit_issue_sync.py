#!/usr/bin/env python3
"""Plan the weekly audit-queue GitHub issues (F-034 surface; pure logic).

All ``gh`` calls stay in the workflow — this script turns three inputs into an
issue plan, so the dedupe/rendering logic is unit-testable offline:

  * ``--selected``         change_ids picked by ``audit_sampler select`` (one per
                           line; sampler logic untouched, I-2). Each line is either
                           ``<change_id>`` or ``<change_id>\t<propensity>`` -- the
                           sampler emits the second form under ``--with-propensity``,
                           and both parse, so an older selection file still works.
  * ``--existing-issues``  JSON from ``gh issue list --state all --json title,state``
                           (closed issues count as handled: closed-as-audited or
                           dismissed audits are never reopened)
  * ``--store``            the synced outcome store, for record context

Output: a JSON list of ``{change_id, title, body}`` for the issues to create.
Bodies offer exactly TWO verdict paths — the Actions UI dispatch and
``gh workflow run`` — both of which sync the store and attribute the actor. The
raw ``audit_sampler`` CLI is deliberately NOT offered: it would write a local
store that never reaches the data branch (a silently-lost verdict).

Exit codes: 0 plan written; 2 unreadable/invalid inputs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from _cli import configure_logging
from agent_core.audit_sampler import format_propensity, is_valid_propensity
from agent_core.outcome_store import OutcomeRecord, OutcomeStore

logger = logging.getLogger(__name__)

ISSUE_TITLE_PREFIX = "merge-gate audit: "
EXIT_OK = 0
EXIT_CONFIG = 2
VERDICT_WORKFLOW = "merge-gate-verdict.yml"


class InputError(RuntimeError):
    """Raised when an input file cannot be read or parsed (exit code 2)."""


@dataclass(frozen=True)
class SelectedChange:
    """One sampled change and the probability it was sampled with, when known.

    ``propensity`` is ``None`` for a selection file written before the sampler emitted
    it. Unknown must stay unknown: inventing a value here would silently corrupt any
    later ``1/p`` reweighting, which is the entire reason the sampler records it.

    The contract is enforced on the *type*, not only on the parse path, so a caller
    constructing one directly cannot smuggle an uninterpretable probability into an issue
    body. ``_read_selected`` still screens its input and downgrades a bad column to
    unknown -- that keeps a malformed file from dropping a change that still deserves an
    audit, and leaves this as defence in depth rather than the only guard.
    """

    change_id: str
    propensity: float | None = None

    def __post_init__(self) -> None:
        if not is_valid_propensity(self.propensity):
            raise ValueError(
                f"selection_propensity must be a finite number in (0, 1] or None "
                f"(got {self.propensity!r} for {self.change_id!r})"
            )


def issue_title(change_id: str) -> str:
    return f"{ISSUE_TITLE_PREFIX}{change_id}"


def audited_change_ids(issues: Sequence[Mapping[str, object]]) -> set[str]:
    """change_ids that already have an audit issue in ANY state; foreign titles
    are tolerated (the label filter upstream is the primary scope)."""
    handled: set[str] = set()
    for issue in issues:
        title = str(issue.get("title", ""))
        if title.startswith(ISSUE_TITLE_PREFIX):
            handled.add(title[len(ISSUE_TITLE_PREFIX) :].strip())
    return handled


def issue_body(rec: OutcomeRecord, repo: str, propensity: float | None = None) -> str:
    label = "pending" if rec.label is None else f"{rec.label} ({rec.label_source})"
    return "\n".join(
        [
            "A merge outcome was randomly sampled for human audit (unbiased sample —",
            "these verdicts are the ONLY labels that feed the auto-merge guarantee).",
            "",
            f"- **change_id**: `{rec.change_id}`",
            f"- **domain**: `{rec.domain}`",
            f"- **merged_at**: `{rec.merged_at}`",
            f"- **raw_confidence**: `{rec.raw_confidence}`",
            f"- **current label**: `{label}`",
            *([] if propensity is None else [f"- **selection_propensity**: `{format_propensity(propensity)}`"]),
            "",
            f"Review the change (`git show {rec.change_id}`) and judge whether it was",
            "**correct** (no defect attributable to it) or **incorrect**.",
            "",
            "## Record your verdict (either path syncs the store and attributes you)",
            "",
            '1. Actions -> "merge-gate verdict" -> Run workflow -> paste the',
            f"   change_id `{rec.change_id}` and pick a verdict, or",
            f"2. `gh workflow run {VERDICT_WORKFLOW} -f change_id={rec.change_id} -f verdict=correct"
            + ("`" if propensity is None else f" -f selection_propensity={format_propensity(propensity)}`"),
            "   (or `verdict=incorrect`).",
            "",
            f"_Repo: {repo}. This issue is closed automatically once the verdict lands._",
        ]
    )


def plan_issues(
    selected: Sequence[SelectedChange | str],
    store: OutcomeStore,
    existing: Sequence[Mapping[str, object]],
    repo: str,
) -> list[dict[str, str]]:
    """Issues to create: selected ids with no existing issue, rendered with
    record context. Ids absent from the store are logged and skipped (the
    selection and the store come from the same pull, so this is defensive)."""
    handled = audited_change_ids(existing)
    resolved = store.resolved()
    plan: list[dict[str, str]] = []
    for raw in selected:
        # A bare change_id is accepted as "propensity unknown", mirroring the tolerance
        # `_read_selected` applies to the file format, so any caller holding plain ids
        # keeps working.
        sel = raw if isinstance(raw, SelectedChange) else SelectedChange(raw)
        change_id = sel.change_id
        if change_id in handled:
            logger.info("audit-issue-sync: %s already has an issue; skipping", change_id)
            continue
        rec = resolved.get(change_id)
        if rec is None:
            logger.warning("audit-issue-sync: %s not in store; skipping", change_id)
            continue
        plan.append(
            {
                "change_id": change_id,
                "title": issue_title(change_id),
                "body": issue_body(rec, repo, sel.propensity),
            }
        )
    logger.info(
        "audit-issue-sync: %d selected, %d already handled, %d to create",
        len(selected),
        len(handled),
        len(plan),
    )
    return plan


def _read_selected(path: str) -> list[SelectedChange]:
    """Parse the sampler's selection file, tolerating both line formats.

    ``<change_id>`` and ``<change_id>\t<propensity>`` both parse, so a file written
    before the sampler grew ``--with-propensity`` still works. A malformed probability
    column is logged and treated as unknown rather than failing the whole queue: the
    change still deserves an audit, it just cannot be reweighted.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
    except OSError as exc:
        raise InputError(f"cannot read --selected '{path}': {exc}") from exc

    out: list[SelectedChange] = []
    for line in lines:
        change_id, _, raw = line.partition("\t")
        propensity: float | None = None
        if raw.strip():
            try:
                parsed = float(raw)
            except ValueError:
                logger.warning(
                    "audit-issue-sync: %s has an unparseable propensity %r; treating as unknown",
                    change_id.strip(),
                    raw.strip(),
                )
            else:
                # `float()` happily accepts "nan", "inf" and any out-of-range number, so
                # parsing is not validation. Reject here, at ingestion, rather than
                # rendering an uninterpretable value into the issue body and a dispatch
                # command that is guaranteed to fail at the recorder.
                if is_valid_propensity(parsed):
                    propensity = parsed
                else:
                    logger.warning(
                        "audit-issue-sync: %s has an out-of-contract propensity %r "
                        "(want a finite number in (0, 1]); treating as unknown",
                        change_id.strip(),
                        parsed,
                    )
        out.append(SelectedChange(change_id.strip(), propensity))
    return out


def _read_existing(path: str) -> list[Mapping[str, object]]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read --existing-issues '{path}': {exc}") from exc
    if not isinstance(data, list):
        raise InputError("--existing-issues must be a JSON list")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Plan merge-gate audit issues.")
    ap.add_argument("--store", required=True)
    ap.add_argument("--selected", required=True, help="file: one change_id per line")
    ap.add_argument("--existing-issues", required=True, help="gh issue list JSON file")
    ap.add_argument("--repo", required=True, help="owner/name, for the issue body")
    ap.add_argument("--output", required=True, help="write the JSON plan here")
    args = ap.parse_args(argv)

    configure_logging()
    try:
        plan = plan_issues(
            _read_selected(args.selected),
            OutcomeStore(args.store),
            _read_existing(args.existing_issues),
            args.repo,
        )
    except InputError as exc:
        logger.error("audit-issue-sync: %s", exc)
        return EXIT_CONFIG
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, sort_keys=True)
        fh.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
