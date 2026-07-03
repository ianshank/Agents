#!/usr/bin/env python3
"""Validation script for F-037 - Monorepo quality-floor remediation.

Asserts the 2026-07-03 branch-sweep remediation stays enforced:
    1. The staged claude-foundation suite is guarded by an ACTIVE root workflow
       (its own .github/ copy is inert inside the monorepo). The workflow and
       the staging directory exist or vanish together: after extraction the
       deletion PR removes both, and this check inverts to "neither remains".
    2. skills-ci type-checks and format-gates all four skills with pinned tools.
    3. The instrumented modules keep their loggers (silent-degrade regression
       guard for the paths the sweep made observable).
    4. The shared strict JSONL reader stays the single read path for
       OutcomeStore.

Deterministic and offline: reads config/workflow/source files only, runs
nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

# Ensure scripts/ and this directory are importable when run directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)

_FOUNDATION_DIR = "claude-foundation"
_FOUNDATION_WORKFLOW = os.path.join(".github", "workflows", "claude-foundation-ci.yml")
# Module -> logger-defining line that must survive (the sweep's observability contract).
_INSTRUMENTED = {
    os.path.join("agent-core", "agent_core", "detectors.py"): "get_logger(__name__)",
    os.path.join("agent-core", "agent_core", "jsonl.py"): "get_logger(__name__)",
    os.path.join("agent-core", "agent_core", "persistence.py"): "get_logger(__name__)",
    os.path.join("src", "eval_harness", "campaign.py"): "logging.getLogger(__name__)",
    os.path.join("behavioral-regression", "behavioral_regression", "gate.py"): "get_logger(",
    os.path.join("flow-corpus", "flow_corpus", "holdout", "manager.py"): "get_logger(",
}


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. Staging CI: workflow and staging dir exist (or vanish) together.
    staging_exists = os.path.isdir(os.path.join(_ROOT, _FOUNDATION_DIR))
    workflow_exists = os.path.exists(os.path.join(_ROOT, _FOUNDATION_WORKFLOW))
    _check(
        staging_exists == workflow_exists,
        "claude-foundation staging dir and its root CI workflow exist or vanish together",
        errors,
    )
    if staging_exists and workflow_exists:
        wf = _read(_FOUNDATION_WORKFLOW)
        for needle, label in (
            ('paths: ["claude-foundation/**"', "workflow is path-filtered on the staging dir"),
            ("ruff check tools tests hooks", "workflow lints the foundation"),
            ("ruff format --check tools tests hooks", "workflow format-checks the foundation"),
            ("mypy tools", "workflow type-checks foundation tools"),
            ("mypy hooks", "workflow type-checks foundation hooks"),
            ("python -m pytest --cov", "workflow runs the foundation suite with coverage"),
        ):
            _check(needle in wf, label, errors)

    # 2. Skills typing + formatting gates, pinned tools.
    skills_ci = _read(os.path.join(".github", "workflows", "skills-ci.yml"))
    _check(
        skills_ci.count("mypy --config-file ../../pyproject.toml") >= 4,
        "skills-ci type-checks all four skills against the root mypy config",
        errors,
    )
    _check(
        skills_ci.count("ruff format --check") >= 4,
        "skills-ci format-gates all four skills",
        errors,
    )
    _check(
        "mypy==" in skills_ci and "ruff==" in skills_ci,
        "skills-ci pins ruff/mypy (no version drift vs the root dev extras)",
        errors,
    )

    # 3. Instrumented modules keep their loggers.
    for rel_path, needle in _INSTRUMENTED.items():
        _check(needle in _read(rel_path), f"{rel_path} keeps its module logger", errors)

    # 4. The shared strict JSONL reader stays OutcomeStore's read path.
    _check(
        "def read_jsonl(" in _read(os.path.join("agent-core", "agent_core", "jsonl.py")),
        "agent_core.jsonl.read_jsonl exists",
        errors,
    )
    _check(
        "read_jsonl" in _read(os.path.join("agent-core", "agent_core", "outcome_store.py")),
        "OutcomeStore delegates reads to the shared reader",
        errors,
    )

    return report(logger, "F-037", errors)


if __name__ == "__main__":
    raise SystemExit(main())
