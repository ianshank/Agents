#!/usr/bin/env python3
"""Validation script for F-043 — agent-records calibration report.

Deterministic and offline: reads the module + workflow text only, runs nothing and
imports no agent_core (the validation gate does not install it). The report's
numerical correctness is covered by agent-core's own test suite.

    1. agent_core/calibration_report.py exists, reuses the calibration primitives
       (auroc / brier_decomposition / wilson_interval / selective_risk_coverage),
       keeps the HUMAN_AUDIT (tau-relevant) view separate from the passive diagnostic
       view, and guards degeneracy (constant predictor / single class) instead of
       emitting the by-construction 0.5.
    2. outcome-labeller.yml surfaces the agent-domain report to the run step summary,
       read-only — the step runs after the store push, so it cannot leave partial state.

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

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_MODULE = os.path.join("agent-core", "agent_core", "calibration_report.py")
_LABELLER = os.path.join(".github", "workflows", "outcome-labeller.yml")


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def validate_f043() -> int:
    configure_logging()
    errors: list[str] = []

    mod = _read(_MODULE)
    for needle, why in [
        ("from .calibration import", "reuses the calibration primitives (no new math)"),
        ("selective_risk_coverage", "abstention via selective risk/coverage"),
        ("wilson_interval", "Wilson CIs on the base rate"),
        ("brier_decomposition", "Brier + Murphy decomposition"),
        ("HUMAN_AUDIT", "primary view filters to the authoritative label (I-1)"),
        ("tau_eligible", "views tag whether they can feed tau (passive kept separate)"),
        ("degenerate", "degeneracy guard instead of a by-construction 0.5"),
    ]:
        _check(needle in mod, f"report module: {why}", errors)

    wf = _read(_LABELLER)
    _check("agent_core.calibration_report" in wf, "labeller surfaces the calibration report", errors)
    _check("--domain-filter agent" in wf, "report is scoped to agent domains", errors)
    _check("GITHUB_STEP_SUMMARY" in wf, "report lands in the run step summary", errors)
    _check(
        wf.rfind("store_sync push") < wf.find("agent_core.calibration_report"),
        "report step runs after the store push (read-only, no partial-state risk)",
        errors,
    )

    return report(logger, "F-043", errors)


def main() -> int:
    return validate_f043()


if __name__ == "__main__":
    sys.exit(main())
