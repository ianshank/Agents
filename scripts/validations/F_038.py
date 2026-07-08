#!/usr/bin/env python3
"""Validation script for F-038 — credential scrub + secret-scan gate (gitleaks).

Deterministic and offline: reads source/config/workflow files only, runs nothing.

    1. The rotated Langfuse key literals no longer survive in the scrubbed files,
       which instead carry the redaction placeholder.
    2. A config-driven ``.gitleaks.toml`` exists (extends the default ruleset, has an
       allowlist) and stores no secret literal itself.
    3. ``quality-gates.yml`` wires gitleaks fail-closed on the working tree
       (``detect --no-git`` + the config) and report-only over history
       (``--exit-code 0``), per ADR 0020.
    4. ADR 0020 (no history rewrite) exists.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
# Match a real Langfuse key (prefix + hex body) without embedding either rotated key.
_KEY_RE = re.compile(r"(sk|pk)-lf-[0-9a-f]{8}")
_SCRUBBED = (
    "HARNESS_SPEC.md",
    os.path.join("docs", "decisions", "0003-langfuse-integration.md"),
    "progress.md",
)
_GITLEAKS_CFG = ".gitleaks.toml"
_WORKFLOW = os.path.join(".github", "workflows", "quality-gates.yml")
_ADR = os.path.join("docs", "decisions", "0020-no-history-rewrite.md")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. Scrubbed files carry no key literal and do carry the placeholder.
    for rel in _SCRUBBED:
        text = _read(rel)
        _check(_KEY_RE.search(text) is None, f"{rel}: no Langfuse key literal survives", errors)
        _check("REDACTED" in text, f"{rel}: carries the redaction placeholder", errors)

    # 2. Config exists, extends the default ruleset + has an allowlist, stores no literal.
    cfg = _read(_GITLEAKS_CFG)
    _check("useDefault = true" in cfg, f"{_GITLEAKS_CFG}: extends the default ruleset", errors)
    _check("[allowlist]" in cfg, f"{_GITLEAKS_CFG}: declares an allowlist", errors)
    _check(_KEY_RE.search(cfg) is None, f"{_GITLEAKS_CFG}: stores no secret literal", errors)

    # 3. Workflow wires gitleaks fail-closed (working tree) + report-only (history).
    wf = _read(_WORKFLOW)
    for needle, why in (
        ("gitleaks detect --no-git", "gitleaks fail-closed on the working tree"),
        ("--config .gitleaks.toml", "the scan is config-driven"),
        ("--exit-code 0", "the history scan is report-only (ADR 0020)"),
    ):
        _check(needle in wf, f"quality-gates.yml: {why}", errors)

    # 4. The no-history-rewrite ADR exists.
    _check(os.path.exists(os.path.join(_ROOT, _ADR)), "ADR 0020 (no history rewrite) exists", errors)

    return report(logger, "F-038", errors)


if __name__ == "__main__":
    raise SystemExit(main())
