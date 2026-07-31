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
       OutcomeStore, and tests/ stay type-checked in every suite's CI.

Checks 1 and 4 assert the *guarantee* (the step runs in that suite's CI), not one wiring
of it -- see ``_common.ci_enforces``. They pass whether the step is inline in the workflow
or delegated to that suite's generated ``scripts/quality-gate.sh`` (ADR 0021). Pinning the
inline spelling made this gate fail the moment the eval-harness delegation landed (PR #64)
even though tests/ were still fully type-checked; because the protected-path guard does not
fire on ``.github/``-only PRs, that failure went undetected on ``main``. Check 2 is
deliberately still inline-matched (no skill has a generated gate yet).

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
from _common import ci_enforces, configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)

_FOUNDATION_DIR = "claude-foundation"
_FOUNDATION_WORKFLOW = os.path.join(".github", "workflows", "claude-foundation-ci.yml")

_WORKFLOWS = os.path.join(".github", "workflows")


def _gate(package: str = "") -> str:
    """Path to a suite's generated quality gate (repo root when ``package`` is empty)."""
    return (
        os.path.join(package, "scripts", "quality-gate.sh") if package else os.path.join("scripts", "quality-gate.sh")
    )


# (workflow, that suite's generated gate, inline spelling, tokens the delegated gate needs).
# Every package gate type-checks both its module and ``tests``, so the delegated form
# asserts both -- matching what the inline "mypy <module> tests" spelling guaranteed.
_TYPECHECK_SUITES = (
    (
        os.path.join(_WORKFLOWS, "eval-harness-ci.yml"),
        _gate(),
        "mypy tests",
        ('mypy "tests"',),
    ),
    (
        os.path.join(_WORKFLOWS, "agent-core-ci.yml"),
        _gate("agent-core"),
        "mypy agent_core tests",
        ('mypy "agent_core"', 'mypy "tests"'),
    ),
    (
        os.path.join(_WORKFLOWS, "flow-corpus-ci.yml"),
        _gate("flow-protocol"),
        "mypy flow_protocol tests",
        ('mypy "flow_protocol"', 'mypy "tests"'),
    ),
    (
        os.path.join(_WORKFLOWS, "flow-corpus-ci.yml"),
        _gate("flow-corpus"),
        "mypy flow_corpus tests",
        ('mypy "flow_corpus"', 'mypy "tests"'),
    ),
    (
        os.path.join(_WORKFLOWS, "behavioral-regression-ci.yml"),
        _gate("behavioral-regression"),
        "mypy behavioral_regression tests",
        ('mypy "behavioral_regression"', 'mypy "tests"'),
    ),
)
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
        _check(
            'paths: ["claude-foundation/**"' in wf,
            "workflow is path-filtered on the staging dir",
            errors,
        )
        # Lint/type/coverage may be inline or delegated to the foundation's own gate.
        foundation_gate_rel = _gate(_FOUNDATION_DIR)
        foundation_gate = _read(foundation_gate_rel) if os.path.exists(os.path.join(_ROOT, foundation_gate_rel)) else ""
        for inline, in_gate, label in (
            ("ruff check tools tests hooks", 'ruff check "."', "workflow lints the foundation"),
            (
                "ruff format --check tools tests hooks",
                'ruff format --check "."',
                "workflow format-checks the foundation",
            ),
            ("mypy tools", 'mypy "tools"', "workflow type-checks foundation tools"),
            ("mypy hooks", 'mypy "hooks"', "workflow type-checks foundation hooks"),
            (
                "python -m pytest --cov",
                "pytest --cov",
                "workflow runs the foundation suite with coverage",
            ),
        ):
            _check(ci_enforces(wf, foundation_gate, inline=inline, in_gate=in_gate), label, errors)

    # 2. Skills typing + formatting gates, pinned tools.
    # Deliberately still matched inline: unlike the five packages, no skill has a generated
    # scripts/quality-gate.sh, so there is no delegated form to assert against yet. When the
    # skills half of ADR 0021 lands (it needs a gategen coverage-contract flag first, since
    # skills ship no pyproject.toml and would otherwise generate a gate with no floor),
    # these three checks must move to ci_enforces() the same way checks 1/4 did.
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

    # 4. tests/ stay type-checked in every suite's CI, and the package configs keep
    # explicit_package_bases (without it the tests.* overrides silently never match).
    # Each entry names the workflow, that suite's generated gate, the inline spelling, and
    # the tokens the delegated gate must contain. ci_enforces() accepts either wiring, so
    # the ADR 0021 fan-out does not re-break this gate the way it broke it on PR #64.
    for wf, gate_rel, inline, in_gate_tokens in _TYPECHECK_SUITES:
        gate = _read(gate_rel) if os.path.exists(os.path.join(_ROOT, gate_rel)) else ""
        ok = all(ci_enforces(_read(wf), gate, inline=inline, in_gate=token) for token in in_gate_tokens)
        _check(ok, f"{wf} type-checks tests ({inline})", errors)
    if workflow_exists:
        foundation_gate = os.path.join(_FOUNDATION_DIR, "scripts", "quality-gate.sh")
        gate = _read(foundation_gate) if os.path.exists(os.path.join(_ROOT, foundation_gate)) else ""
        _check(
            ci_enforces(_read(_FOUNDATION_WORKFLOW), gate, inline="mypy tests", in_gate='mypy "tests"'),
            "claude-foundation staging CI type-checks tests",
            errors,
        )
    for pkg in ("agent-core", "flow-protocol", "flow-corpus", "behavioral-regression"):
        _check(
            "explicit_package_bases = true" in _read(os.path.join(pkg, "pyproject.toml")),
            f"{pkg} pyproject keeps explicit_package_bases (tests.* override stays live)",
            errors,
        )

    # 5. The shared strict JSONL reader stays OutcomeStore's read path.
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
