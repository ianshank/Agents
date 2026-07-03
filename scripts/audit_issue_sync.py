#!/usr/bin/env python3
"""Plan the weekly audit-queue GitHub issues (F-034 surface; pure logic).

All ``gh`` calls stay in the workflow — this script turns three inputs into an
issue plan, so the dedupe/rendering logic is unit-testable offline:

  * ``--selected``         change_ids picked by ``audit_sampler select`` (one per
                           line; sampler logic untouched, I-2)
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

from _cli import configure_logging
from agent_core.outcome_store import OutcomeRecord, OutcomeStore

logger = logging.getLogger(__name__)

ISSUE_TITLE_PREFIX = "merge-gate audit: "
EXIT_OK = 0
EXIT_CONFIG = 2
VERDICT_WORKFLOW = "merge-gate-verdict.yml"


class InputError(RuntimeError):
    """Raised when an input file cannot be read or parsed (exit code 2)."""


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


def issue_body(rec: OutcomeRecord, repo: str) -> str:
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
            "",
            f"Review the change (`git show {rec.change_id}`) and judge whether it was",
            "**correct** (no defect attributable to it) or **incorrect**.",
            "",
            "## Record your verdict (either path syncs the store and attributes you)",
            "",
            '1. Actions -> "merge-gate verdict" -> Run workflow -> paste the',
            f"   change_id `{rec.change_id}` and pick a verdict, or",
            f"2. `gh workflow run {VERDICT_WORKFLOW} -f change_id={rec.change_id} -f verdict=correct`",
            "   (or `verdict=incorrect`).",
            "",
            f"_Repo: {repo}. This issue is closed automatically once the verdict lands._",
        ]
    )


def plan_issues(
    selected: Sequence[str],
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
    for change_id in selected:
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
                "body": issue_body(rec, repo),
            }
        )
    logger.info(
        "audit-issue-sync: %d selected, %d already handled, %d to create",
        len(selected),
        len(handled),
        len(plan),
    )
    return plan


def _read_selected(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError as exc:
        raise InputError(f"cannot read --selected '{path}': {exc}") from exc


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
