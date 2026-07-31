#!/usr/bin/env python3
"""One-off backfill: re-domain already-merged agent changes into their agent domain.

F-044, ADR 0023 §4. Dated 2026-07-22 (see ``agent-backfill-2026-07-22.txt``).

Every change that landed before F-042 was seeded as ``human/<domain>`` at confidence
0.0 by the ``--human``-only seeder — a KNOWN MISLABEL for the ~18 agent-authored
(``claude/*``) merges. This migration corrects them: for each hand-verified change_id it
re-domains ALL its records from ``human/<d>`` -> ``<d>``, sets a deterministic proxy
confidence recomputed over the change's diff (the SAME proxy as live seeding, so forward
and migrated rows are identical), and stamps ``agent_version``.

Why a rewrite (not an append): the store is append-only and idempotent by change_id, and
``store_sync push`` unions with the remote — appending corrected rows would leave the old
mislabeled rows in place (and a push would resurrect them). Correcting the mislabel means
rewriting the canonical store file.

SAFETY (ADR 0023 §4):
  * dry-run by DEFAULT — prints the full before/after diff for human review; writes nothing.
  * ``--apply`` is required to write, and first copies the store to ``<store>.pre-backfill.bak``.
  * NEVER rewrites a HUMAN_AUDIT record (raises instead) and skips already-agent rows
    (idempotent — re-running yields a byte-identical store).
  * does NOT push. The remote rewrite is a deliberate, snapshot-guarded manual step; this
    tool prints that runbook. The data branch's own git history is the durable snapshot.

Usage::

    # 1. pull the store locally
    python -m agent_core.store_sync pull --store merge_outcomes.jsonl --repo-dir .
    # 2. review the dry-run diff
    python scripts/migrations/agent_domain_backfill.py \
        --store merge_outcomes.jsonl \
        --shas-file scripts/migrations/agent-backfill-2026-07-22.txt --repo-dir .
    # 3. apply locally, then follow the printed snapshot + force-push runbook
    python scripts/migrations/agent_domain_backfill.py --store merge_outcomes.jsonl \
        --shas-file scripts/migrations/agent-backfill-2026-07-22.txt --repo-dir . --apply
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import sys
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import agent_confidence as ac
from _cli import configure_logging
from agent_core.domains import strip_human_namespace
from agent_core.outcome_store import LabelSource, OutcomeRecord
from agent_core.store_sync.store import read_store_lines, write_store
from agent_core.subprocess_util import run_failsafe

logger = logging.getLogger(__name__)

_GIT_TIMEOUT_S = 30.0

EXIT_OK = 0
EXIT_CONFIG = 2


@dataclass(frozen=True)
class BackfillTarget:
    agent_version: str
    confidence: float


@dataclass(frozen=True)
class ChangeDiff:
    change_id: str
    old_domain: str
    new_domain: str
    old_confidence: float
    new_confidence: float


def plan_backfill(
    records: list[OutcomeRecord], targets: dict[str, BackfillTarget]
) -> tuple[list[OutcomeRecord], list[ChangeDiff]]:
    """Pure: re-domain every record of a targeted change_id. Refuses HUMAN_AUDIT.

    Returns (new_records, diffs). Idempotent: a record already in its agent domain with
    the target confidence/agent_version is unchanged and produces no diff row.
    """
    new_records: list[OutcomeRecord] = []
    diffs: list[ChangeDiff] = []
    for r in records:
        target = targets.get(r.change_id)
        if target is None:
            new_records.append(r)
            continue
        if r.label_source == LabelSource.HUMAN_AUDIT.value:
            raise ValueError(f"refusing to rewrite a HUMAN_AUDIT record ({r.change_id}): audits are authoritative")
        new_domain = strip_human_namespace(r.domain)
        updated = dataclasses.replace(
            r, domain=new_domain, raw_confidence=target.confidence, agent_version=target.agent_version
        )
        new_records.append(updated)
        if updated != r:
            diffs.append(ChangeDiff(r.change_id, r.domain, new_domain, r.raw_confidence, target.confidence))
    return new_records, diffs


def parse_shas_file(text: str) -> dict[str, str]:
    """Parse '<change_id> <agent_version>' lines (# comments allowed) -> {id: agent_version}.

    Every line MUST carry an explicit agent_version; a bare SHA is a malformed list and raises,
    matching the committed file format and the F-044 safety envelope (no silent default).
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"backfill SHA line must be '<change_id> <agent_version>'; got {line!r}")
        out[parts[0]] = parts[1]
    return out


def _git(args: list[str], repo_dir: str) -> str:
    """Run ``git -C <repo_dir> <args>`` via the shared fail-safe runner; raise on failure."""
    result = run_failsafe(["git", "-C", repo_dir, *args], _GIT_TIMEOUT_S)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} in {repo_dir!r} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return str(result.stdout)


def compute_confidence_for(change_id: str, repo_dir: str, proxy: ac.ProxyConfig) -> float:
    """Recompute the proxy confidence over the change's diff vs its first parent."""
    files = [f for f in _git(["diff", "--name-only", f"{change_id}^", change_id], repo_dir).splitlines() if f.strip()]
    lines = 0
    for row in _git(["diff", "--numstat", f"{change_id}^", change_id], repo_dir).splitlines():
        cols = row.split("\t")
        for n in cols[:2]:
            if n.isdigit():
                lines += int(n)
    return float(ac.compute_confidence(files, lines, proxy))


def build_targets(shas: dict[str, str], repo_dir: str, proxy: ac.ProxyConfig) -> dict[str, BackfillTarget]:
    return {
        cid: BackfillTarget(agent_version=av, confidence=compute_confidence_for(cid, repo_dir, proxy))
        for cid, av in shas.items()
    }


def render_diff(diffs: list[ChangeDiff]) -> str:
    if not diffs:
        return "(no changes — store already reflects the agent domains; nothing to do)"
    lines = ["change_id      old_domain -> new_domain                 conf"]
    for d in diffs:
        lines.append(
            f"{d.change_id[:12]}  {d.old_domain:>22} -> {d.new_domain:<16} {d.old_confidence:.3f} -> {d.new_confidence:.3f}"
        )
    return "\n".join(lines)


def _runbook(store: str) -> str:
    return (
        "\nLocal store rewritten. The remote rewrite is a deliberate, snapshot-guarded step:\n"
        "  1. snapshot (reversible):  git -C <data-branch-checkout> tag backfill-pre-2026-07-22\n"
        f"  2. copy the corrected {store} onto the merge-gate-data branch checkout\n"
        "  3. commit + push that branch (a force-update, NOT store_sync push, which would union\n"
        "     the old rows back). Review the commit diff before pushing.\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-off agent-domain backfill (F-044).")
    ap.add_argument("--store", required=True, help="local outcome store JSONL (pull it first)")
    ap.add_argument("--shas-file", required=True, help="hand-verified '<change_id> <agent_version>' list")
    ap.add_argument("--repo-dir", default=".", help="git repo for diff-based confidence recompute")
    # Reuse the live seeder's default so a config relocation can't silently make migrated rows
    # use different weights than forward rows (the "forward == migrated" invariant this tool sells).
    ap.add_argument("--proxy-config", default=ac.DEFAULT_PROXY_PATH)
    ap.add_argument("--apply", action="store_true", help="write the corrected store (default: dry-run)")
    args = ap.parse_args(argv)
    configure_logging()
    logger.info(
        "backfill: store=%s shas=%s repo_dir=%s mode=%s",
        args.store,
        args.shas_file,
        args.repo_dir,
        "apply" if args.apply else "dry-run",
    )

    # Load + recompute can fail on a missing store / bad shas file / bad proxy config / git
    # error. All abort before any write (fail toward no-op); surface them as a clean exit 2
    # matching the sibling CLIs, not a raw traceback. ConfigError subclasses RuntimeError, so
    # RuntimeError also covers _git's failure and ProxyConfig.load.
    try:
        records, opaque = read_store_lines(args.store)
        with open(args.shas_file, encoding="utf-8") as fh:
            shas = parse_shas_file(fh.read())
        proxy = ac.ProxyConfig.load(args.proxy_config)
        targets = build_targets(shas, args.repo_dir, proxy)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.error("backfill: %s", exc)
        return EXIT_CONFIG

    logger.info("backfill: %d target change_ids resolved, %d records in store", len(targets), len(records))
    present = {r.change_id for r in records}
    missing = sorted(cid for cid in targets if cid not in present)
    if missing:
        logger.warning("%d target change_ids are not in the store (skipped): %s", len(missing), missing)

    new_records, diffs = plan_backfill(records, targets)
    n_changed_ids = len({d.change_id for d in diffs})
    print(render_diff(diffs))

    if not args.apply:
        print(f"\n{len(diffs)} records would change across {n_changed_ids} change_ids.")
        print("\n(dry-run — pass --apply to write the corrected store locally)")
        return EXIT_OK

    backup = args.store + ".pre-backfill.bak"
    shutil.copyfile(args.store, backup)
    write_store(args.store, new_records, opaque)
    logger.info(
        "backfill applied: rewrote %d records across %d change_ids; backup=%s", len(diffs), n_changed_ids, backup
    )
    print(f"\nrewrote {len(diffs)} records across {n_changed_ids} change_ids.")
    print(f"wrote {args.store} (backup at {backup})")
    print(_runbook(args.store))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
