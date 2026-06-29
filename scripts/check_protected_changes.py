#!/usr/bin/env python3
"""CI guard: flag PRs that touch eval-defining (protected) paths without approval.

Changing a protected path (see ``eval_protected_paths.py``) is legitimate — but it
must be a deliberate, human-reviewed act, never a side effect of an automated
"fix-until-green" step. This guard surfaces such changes and requires an explicit
approval signal (a PR label, by default ``eval-change-approved``) before allowing
the build to pass. GitHub CODEOWNERS provides the complementary, review-time
enforcement; this script makes the invariant mechanical in CI.

Inputs are resolved dynamically so the script works locally and in CI:
    * changed files: ``--files`` (testing) else ``git diff --name-only <base>...HEAD``
    * base ref:      ``--base-ref`` else ``$BASE_REF`` else ``origin/main``
    * approval:      ``--approved`` flag, or the approval label present in
                     ``--labels`` / ``$PR_LABELS`` (comma/space/JSON list)

Exit codes:
    0 – no protected paths changed, or change is approved
    1 – protected paths changed without approval
    2 – configuration error (could not determine the changed file set)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from collections.abc import Sequence

from _cli import configure_logging
from eval_protected_paths import matched_protected

logger = logging.getLogger(__name__)

DEFAULT_BASE_REF: str = "origin/main"
DEFAULT_APPROVAL_LABEL: str = "eval-change-approved"


class ConfigError(RuntimeError):
    """Raised when the changed file set cannot be determined (exit code 2)."""


def parse_labels(raw: str | None) -> set[str]:
    """Parse a label list that may be JSON, comma-, or whitespace-separated."""
    if not raw:
        return set()
    raw = raw.strip()
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        labels: set[str] = set()
        for item in data:
            if isinstance(item, dict):  # GitHub label objects
                name = item.get("name")
                if name:
                    labels.add(str(name))
            elif item:
                labels.add(str(item))
        return labels
    return {tok for tok in raw.replace(",", " ").split() if tok}


def changed_files_from_git(base_ref: str) -> list[str]:
    """Return files changed relative to *base_ref* using a merge-base diff."""
    for diff_spec in (f"{base_ref}...HEAD", f"{base_ref}..HEAD", base_ref):
        proc = subprocess.run(
            ["git", "diff", "--name-only", diff_spec],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line.strip()]
        logger.debug("git diff %s failed: %s", diff_spec, proc.stderr.strip())
    raise ConfigError(
        f"could not compute changed files against base ref '{base_ref}' (is the ref fetched? try --files for local use)"
    )


def resolve_changed_files(args: argparse.Namespace) -> list[str]:
    """Resolve the changed file set from explicit input or git."""
    if args.files:
        return [f for f in args.files if f.strip()]
    base_ref = args.base_ref or os.environ.get("BASE_REF") or DEFAULT_BASE_REF
    return changed_files_from_git(base_ref)


def approval_source(args: argparse.Namespace) -> str | None:
    """Return a human-readable description of the approval signal, or None if absent."""
    if args.approved:
        return "--approved flag"
    raw = args.labels if args.labels is not None else os.environ.get("PR_LABELS")
    if args.approval_label in parse_labels(raw):
        return f"label '{args.approval_label}'"
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--files", nargs="*", default=None, help="Explicit changed file list (testing/local)")
    parser.add_argument(
        "--base-ref", default=None, help=f"Base ref for diff (default: $BASE_REF or {DEFAULT_BASE_REF})"
    )
    parser.add_argument("--labels", default=None, help="PR labels (JSON/comma/space list); default $PR_LABELS")
    parser.add_argument("--approval-label", default=DEFAULT_APPROVAL_LABEL, help="Label that signals approval")
    parser.add_argument("--approved", action="store_true", help="Force-approve (explicit human override)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        changed = resolve_changed_files(args)
    except ConfigError as exc:
        print(f"protected-guard: configuration error: {exc}")
        return 2

    protected = matched_protected(changed)
    if not protected:
        print("protected-guard: OK — no eval-defining paths changed.")
        return 0

    source = approval_source(args)
    if source is not None:
        print(f"protected-guard: OK — {len(protected)} protected path(s) changed, approved via {source}.")
        for path in protected:
            print(f"  - {path}")
        return 0

    print("protected-guard: BLOCKED — protected eval-defining paths changed without approval:")
    for path in protected:
        print(f"  - {path}")
    print(
        f"\nThese files define the evaluation surface. A human must review and add the "
        f"'{args.approval_label}' label (CODEOWNERS review also applies) before merge."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
