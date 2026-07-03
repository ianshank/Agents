"""Release gate over skill-creator eval results.

The plugin does not reimplement an eval runner (ADR 0003): behavioral evals are
executed by the official skill-creator tooling, which writes ``grading.json``
next to each skill's ``evals/evals.json``. This gate reads those reports and
fails when any case failed — and, in ``--require-grading`` mode (release), when
any skill has evals but no grading report yet.

Usage: ``python -m foundation_tools.eval_gate [--root PATH] [--require-grading]``
Exit codes: 0 gate passes; 1 failures/missing reports; 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from foundation_tools.jsonlog import get_logger
from foundation_tools.schemas import EvalSuite, GradingReport

logger = get_logger("foundation.eval_gate")


def gate_skill(skill_dir: Path, *, require_grading: bool) -> list[str]:
    """Return gate findings for one skill directory."""
    findings: list[str] = []
    evals_path = skill_dir / "evals" / "evals.json"
    grading_path = skill_dir / "evals" / "grading.json"
    if not evals_path.exists():
        return [f"{skill_dir.name}: missing evals/evals.json"]
    try:
        suite = EvalSuite.model_validate(json.loads(evals_path.read_text("utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        return [f"{skill_dir.name}: unreadable evals.json ({exc})"]

    if not grading_path.exists():
        if require_grading:
            findings.append(
                f"{skill_dir.name}: no grading.json — run the skill-creator evals before release"
            )
        else:
            logger.info("no grading yet; skipping", extra={"skill": skill_dir.name})
        return findings

    try:
        report = GradingReport.model_validate(json.loads(grading_path.read_text("utf-8")))
    except (json.JSONDecodeError, ValidationError) as exc:
        return [f"{skill_dir.name}: unreadable grading.json ({exc})"]

    graded_ids = {graded.id for graded in report.cases}
    for case in suite.cases:
        if case.id not in graded_ids:
            findings.append(f"{skill_dir.name}: case '{case.id}' has no grading result")
    for graded in report.cases:
        if not graded.passed:
            findings.append(
                f"{skill_dir.name}: case '{graded.id}' FAILED"
                + (f" — {graded.evidence}" if graded.evidence else "")
            )
    return findings


def gate_tree(root: Path, *, require_grading: bool) -> list[str]:
    """Gate every skill under ``root/skills``."""
    skills_dir = root / "skills"
    findings: list[str] = []
    if not skills_dir.is_dir():
        return [f"no skills directory under {root}"]
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        found = gate_skill(skill_dir, require_grading=require_grading)
        findings.extend(found)
        logger.info("skill gated", extra={"skill": skill_dir.name, "findings": len(found)})
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="plugin root (default: cwd)")
    parser.add_argument(
        "--require-grading",
        action="store_true",
        help="fail when a skill has no grading.json (release mode)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    findings = gate_tree(root, require_grading=args.require_grading)
    if findings:
        print("EVAL GATE FAILED:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("foundation-eval-gate: OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
