#!/usr/bin/env python3
"""CI guard: assert vendored skill-script copies stay byte-identical to their canonical source.

Some helper scripts are intentionally **duplicated** into individual skills so each skill
stays self-contained and independently vendorable (it can be copied out of this repo and
still run). The cost of that choice is silent drift: a fix applied to one copy and not the
others. This guard removes that risk without removing the duplication — it pins each copy
to a single canonical source and fails loudly when they diverge.

The canonical source for every duplicated script lives under the repo-root ``scripts/``
directory; the skill copies live under ``skills/<skill>/scripts/``.

  python scripts/check_skill_script_drift.py            # check, human-readable report
  python scripts/check_skill_script_drift.py --json     # machine-readable report

Exit codes:
    0 - every tracked copy matches its canonical source (or no copies are tracked)
    1 - at least one copy drifted, is missing, or the canonical source is missing
    2 - configuration / usage error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from _cli import configure_logging

logger = logging.getLogger(__name__)

# Tracked duplications: canonical path -> the vendored skill copies, all relative to the
# repo root. Add an entry here whenever a script is intentionally copied into a skill.
# Keeping this declarative makes the guard reusable for any future duplicated tooling.
TRACKED_DUPLICATES: dict[str, tuple[str, ...]] = {
    "scripts/validate_skill.py": (
        "skills/openai-judge/scripts/validate_skill.py",
        "skills/architecture-drift-guard/scripts/validate_skill.py",
        "skills/eval-corpus-forge/scripts/validate_skill.py",
    ),
}


@dataclass(frozen=True)
class DriftResult:
    """Outcome for a single canonical/copy pair."""

    canonical: str
    copy: str
    status: str  # "ok" | "drift" | "missing_copy" | "missing_canonical"

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _repo_root() -> Path:
    """Return the repo root (parent of the ``scripts/`` directory holding this file)."""
    return Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*'s bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_drift(
    tracked: dict[str, tuple[str, ...]] | None = None,
    *,
    root: Path | None = None,
) -> list[DriftResult]:
    """Compare every tracked copy against its canonical source.

    Args:
        tracked: Mapping of canonical path -> vendored copy paths (repo-relative).
            Defaults to :data:`TRACKED_DUPLICATES` (resolved at call time).
        root: Repo root to resolve paths against; defaults to this file's repo root.

    Returns:
        One :class:`DriftResult` per canonical/copy pair, in declaration order.
    """
    tracked = TRACKED_DUPLICATES if tracked is None else tracked
    base = root if root is not None else _repo_root()
    results: list[DriftResult] = []
    for canonical_rel, copies in tracked.items():
        canonical_path = base / canonical_rel
        canonical_exists = canonical_path.is_file()
        canonical_digest = _sha256(canonical_path) if canonical_exists else None
        if not canonical_exists:
            logger.error("canonical source missing: %s", canonical_rel)
        for copy_rel in copies:
            copy_path = base / copy_rel
            if not canonical_exists:
                results.append(DriftResult(canonical_rel, copy_rel, "missing_canonical"))
                continue
            if not copy_path.is_file():
                logger.error("tracked copy missing: %s", copy_rel)
                results.append(DriftResult(canonical_rel, copy_rel, "missing_copy"))
                continue
            if _sha256(copy_path) == canonical_digest:
                logger.debug("ok: %s matches %s", copy_rel, canonical_rel)
                results.append(DriftResult(canonical_rel, copy_rel, "ok"))
            else:
                logger.error("drift: %s differs from canonical %s", copy_rel, canonical_rel)
                results.append(DriftResult(canonical_rel, copy_rel, "drift"))
    return results


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Assert vendored skill-script copies match their canonical source.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON report on stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the drift check and return an exit code."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    results = check_drift()
    failures = [r for r in results if not r.ok]

    if args.json:
        print(json.dumps([r.__dict__ for r in results], indent=2, sort_keys=True))
    elif not results:
        print("skill-drift: OK - no duplicated scripts tracked.")
    elif not failures:
        print(f"skill-drift: OK - {len(results)} copy/copies match their canonical source.")
    else:
        print(f"skill-drift: FAIL - {len(failures)} of {len(results)} copy/copies drifted:")
        for r in failures:
            print(f"  [{r.status}] {r.copy} (canonical: {r.canonical})")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
