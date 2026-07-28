#!/usr/bin/env python3
"""Validation script for F-042 — agent-authored merge-gate seeding (proxy + routing).

Deterministic and offline: loads the committed configs, exercises the pure proxy, and
reads the seed-workflow text. No network, no git.

    1. config/agent-authors.yaml + config/agent-confidence.yaml load under their strict
       schemas; the claude/ head-ref prefix resolves to an agent_version and human
       branches do not.
    2. The confidence proxy is non-degenerate: distinct changes yield distinct
       confidences, all strictly inside (0, 1).
    3. merge-gate-seed.yml routes by head ref: it invokes agent_confidence.py, has an
       agent lane (--confidence + --agent-version) AND a preserved human fallback lane
       (--human), requests the load-bearing pull-requests: read scope, and logs the lane
       to the step summary.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_confidence as ac
import yaml
from _common import check as _check
from _common import configure_logging, report
from check_protected_changes import ConfigError

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_IDENTITY = os.path.join(_ROOT, "config", "agent-authors.yaml")
_PROXY = os.path.join(_ROOT, "config", "agent-confidence.yaml")
_SEED_WF = os.path.join(_ROOT, ".github", "workflows", "merge-gate-seed.yml")


def _validate_configs(errors: list[str]) -> None:
    try:
        ident = ac.AgentIdentity.load(_IDENTITY)
    except ConfigError as exc:
        _check(False, f"agent-authors.yaml loads under its schema ({exc})", errors)
        return
    _check(ident.resolve("claude/x", "ianshank") == "claude-code", "claude/ head-ref resolves to claude-code", errors)
    _check(ident.resolve("fix/x", "ianshank") is None, "human branches resolve to no agent", errors)

    try:
        cfg = ac.ProxyConfig.load(_PROXY)
    except ConfigError as exc:
        _check(False, f"agent-confidence.yaml loads under its schema ({exc})", errors)
        return
    small = ac.compute_confidence(["pkg/a.py"], 20, cfg)
    big = ac.compute_confidence([f"pkg/{i}.py" for i in range(30)], 5000, cfg)
    _check(0.0 < small < 1.0 and 0.0 < big < 1.0, "proxy confidence stays strictly inside (0,1)", errors)
    _check(small != big, "proxy confidence varies across changes (non-degenerate predictor)", errors)


def _validate_workflow(errors: list[str]) -> None:
    with open(_SEED_WF, encoding="utf-8") as fh:
        text = fh.read()
    doc = yaml.safe_load(text)
    perms = doc.get("permissions", {})
    _check(perms.get("pull-requests") == "read", "seed workflow requests pull-requests: read (routing lookup)", errors)
    _check(perms.get("contents") == "write", "seed workflow keeps contents: write (store push)", errors)
    for needle, why in [
        ("agent_confidence.py", "routing invokes the confidence proxy"),
        ("--confidence", "agent lane uses the confidence seam (no --human)"),
        ("--agent-version", "agent lane records agent_version onto the seed"),
        ("--human", "human fallback lane is preserved"),
        ("commits/${GITHUB_SHA}/pulls", "head ref resolved from the associated PR"),
        ("GITHUB_STEP_SUMMARY", "seed lane logged to the step summary (visible fallback)"),
    ]:
        _check(needle in text, f"seed workflow: {why}", errors)


def validate_f042() -> int:
    configure_logging()
    errors: list[str] = []
    _validate_configs(errors)
    _validate_workflow(errors)
    return report(logger, "F-042", errors)


def main() -> int:
    return validate_f042()


if __name__ == "__main__":
    sys.exit(main())
