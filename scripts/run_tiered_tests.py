#!/usr/bin/env python3
"""Tiered Test Runner and Failure Triage Engine.

Runs tests segregated into four distinct tiers:
  Tier 1: Tests without mocks (pure offline algorithmic, contract, invariants)
  Tier 2: Tests with deterministic mocks (matrix evaluators, mock judges, echo targets)
  Tier 3: Full offline E2E user journeys (validate.py, CLI journeys, run_all_e2e.ps1)
  Tier 4: Live integration smoke tests (credential-gated with EX_CONFIG=78 verification)

Captures failure telemetry, classifies root causes into structured categories
(CAT-ENV, CAT-INVAR, CAT-LOGIC, CAT-LIVE), and emits consolidated markdown/JSON
triage reports.

Complies with the ADR 0019 500-line size budget and ADR 0009 zero hardcoded values.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_tiered_tests")


@dataclass
class StepSpec:
    tier: str
    name: str
    command: list[str]
    timeout_sec: int = 300


@dataclass
class StepResult:
    tier: str
    name: str
    command: list[str]
    status: str  # PASS, FAIL, SKIP
    duration_ms: int
    category: str | None = None  # CAT-ENV, CAT-INVAR, CAT-LOGIC, CAT-LIVE
    error_signature: str = ""
    stdout: str = ""
    stderr: str = ""


@dataclass
class TriageReport:
    timestamp: str
    total_steps: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[StepResult] = field(default_factory=list)


def classify_failure(output: str) -> str:
    """Classify failure output into a diagnostic category."""
    lower = output.lower()
    if "modulenotfounderror" in lower or "importerror" in lower or "no module named" in lower:
        return "CAT-ENV"
    if "exceeds the 500-line" in lower or "charter-invariants" in lower or "charter-drift" in lower:
        return "CAT-INVAR"
    if "stale" in lower or "matrix coverage" in lower:
        return "CAT-INVAR"
    if "connectionerror" in lower or "timeout" in lower or "rate limit" in lower:
        return "CAT-LIVE"
    if "assertionerror" in lower or "failed" in lower:
        return "CAT-LOGIC"
    return "CAT-UNKNOWN"


def run_step(spec: StepSpec) -> StepResult:
    logger.info(
        "[%s] Starting: %s -> %s (timeout: %ds)", spec.tier, spec.name, " ".join(spec.command), spec.timeout_sec
    )
    env = os.environ.copy()
    # Inject e2e_shims to avoid Windows WMI hangs
    shims = str(REPO_ROOT / "scripts" / "e2e_shims")
    cur_pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{shims}{os.pathsep}{cur_pypath}" if cur_pypath else shims

    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            spec.command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=spec.timeout_sec,
            env=env,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        out = (proc.stdout + "\n" + proc.stderr).strip()

        # Exit code 78 is EX_CONFIG (SKIP)
        if proc.returncode == 78:
            logger.warning("[%s] SKIP: %s (exit 78: not configured)", spec.tier, spec.name)
            return StepResult(
                spec.tier, spec.name, spec.command, "SKIP", elapsed_ms, stdout=proc.stdout, stderr=proc.stderr
            )

        if proc.returncode == 0:
            logger.info("[%s] PASS: %s (%d ms)", spec.tier, spec.name, elapsed_ms)
            return StepResult(
                spec.tier, spec.name, spec.command, "PASS", elapsed_ms, stdout=proc.stdout, stderr=proc.stderr
            )

        cat = classify_failure(out)
        sig = out.splitlines()[-1] if out.splitlines() else "Unknown exit code"
        logger.error("[%s] FAIL: %s [%s] (%d ms)", spec.tier, spec.name, cat, elapsed_ms)
        return StepResult(
            spec.tier,
            spec.name,
            spec.command,
            "FAIL",
            elapsed_ms,
            category=cat,
            error_signature=sig,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("[%s] TIMEOUT: %s (%d ms)", spec.tier, spec.name, elapsed_ms)
        return StepResult(
            spec.tier,
            spec.name,
            spec.command,
            "FAIL",
            elapsed_ms,
            category="CAT-LIVE",
            error_signature=f"Timeout after {spec.timeout_sec}s",
            stderr=str(exc),
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.error("[%s] ERROR: %s (%s)", spec.tier, spec.name, exc)
        return StepResult(
            spec.tier,
            spec.name,
            spec.command,
            "FAIL",
            elapsed_ms,
            category="CAT-ENV",
            error_signature=str(exc),
            stderr=str(exc),
        )


def get_tier_steps(tier: str, py: str) -> list[StepSpec]:
    steps: list[StepSpec] = []

    if tier in ("1", "no-mock", "all"):
        t = "TIER-1 (No-Mock)"
        steps.extend(
            [
                StepSpec(t, "Charter Invariants", [py, "scripts/check_charter_invariants.py"]),
                StepSpec(t, "Charter Drift", [py, "scripts/check_charter_drift.py"]),
                StepSpec(t, "Size Budget", [py, "scripts/check_size_budget.py"]),
                StepSpec(t, "Guard Reachability", [py, "scripts/check_guard_reachability.py"]),
                StepSpec(t, "Matrix Coverage Freshness", [py, "tests/test_matrix_coverage.py", "--check"]),
                StepSpec(t, "RCA Corpus Freshness", [py, "scripts/gen_rca_corpus.py", "--check"]),
                StepSpec(t, "Requirements Corpus Freshness", [py, "scripts/gen_requirements_corpus.py", "--check"]),
                StepSpec(t, "TestGen Corpus Freshness", [py, "scripts/gen_testgen_corpus.py", "--check"]),
                StepSpec(
                    t,
                    "Trajectory Determinism Contracts",
                    [py, "-m", "pytest", "tests/test_trajectory_contracts.py", "-q"],
                ),
                StepSpec(
                    t,
                    "Agent-Core Calibration Unit Suite",
                    [py, "-m", "pytest", "agent-core/tests/test_calibration.py", "-q"],
                ),
                StepSpec(t, "Agent-Core PPI Estimators", [py, "-m", "pytest", "agent-core/tests/test_ppi.py", "-q"]),
                StepSpec(t, "Flow-Protocol Unit Suite", [py, "-m", "pytest", "flow-protocol/tests", "-q"]),
            ]
        )

    if tier in ("2", "mock", "all"):
        t = "TIER-2 (Mock-Assisted)"
        steps.extend(
            [
                StepSpec(
                    t, "Matrix Evaluation Tools Suite", [py, "-m", "pytest", "tests/test_matrix_eval_tools.py", "-q"]
                ),
                StepSpec(
                    t, "Anthropic Judge Offline Mocks", [py, "-m", "pytest", "tests/test_anthropic_judge.py", "-q"]
                ),
                StepSpec(t, "OpenAI Judge Offline Mocks", [py, "-m", "pytest", "tests/test_openai_judge.py", "-q"]),
                StepSpec(t, "Budgeted Judge Mocks", [py, "-m", "pytest", "tests/test_budgeted_judge.py", "-q"]),
                StepSpec(t, "Phoenix Client Smoke Tests", [py, "-m", "pytest", "tests/test_phoenix_smoke.py", "-q"]),
                StepSpec(t, "Langfuse Smoke Tests", [py, "-m", "pytest", "tests/test_langfuse_smoke.py", "-q"]),
                StepSpec(t, "Braintrust Scorer Mocks", [py, "-m", "pytest", "tests/test_braintrust_scorer.py", "-q"]),
                StepSpec(t, "Claude Hooks Execution Suite", [py, "-m", "pytest", "tests/test_claude_hooks.py", "-q"]),
            ]
        )

    if tier in ("3", "e2e", "all"):
        t = "TIER-3 (Full E2E Journeys)"
        steps.extend(
            [
                StepSpec(
                    t,
                    "Fast Feature Validators (66 Features)",
                    [py, "scripts/validate.py", "--tier", "fast"],
                    timeout_sec=600,
                ),
                StepSpec(
                    t,
                    "Pipeline Integration E2E",
                    [py, "-m", "pytest", "tests/integration/test_pipeline_e2e.py", "-q"],
                    timeout_sec=300,
                ),
                StepSpec(
                    t,
                    "All E2E Journeys (Offline Tiers A-C)",
                    ["powershell", "-NoProfile", "-File", "scripts/run_all_e2e.ps1", "-Tiers", "offline"],
                    timeout_sec=1800,
                ),
            ]
        )

    if tier in ("4", "live", "all"):
        t = "TIER-4 (Live Smoke Triage)"
        steps.extend(
            [
                StepSpec(
                    t,
                    "Live Integration Smokes (EX_CONFIG Gated)",
                    ["powershell", "-NoProfile", "-File", "scripts/run_all_e2e.ps1", "-Tiers", "all"],
                    timeout_sec=1800,
                ),
            ]
        )

    return steps


def write_report(report: TriageReport, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "triage-report.json"
    md_path = out_dir / "triage-report.md"

    # Write JSON
    json_path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

    # Write Markdown
    lines = [
        "# Tiered Test & Triage Report",
        "",
        f"**Generated:** {report.timestamp}  ",
        f"**Summary:** Total: `{report.total_steps}` | Passed: `{report.passed}` | Failed: `{report.failed}` | Skipped: `{report.skipped}`",
        "",
        "## Execution Results by Tier",
        "",
        "| Tier | Step | Status | Duration (ms) | Category | Failure Signature |",
        "| :--- | :--- | :---: | :---: | :---: | :--- |",
    ]

    for r in report.results:
        cat = r.category or "-"
        sig = f"`{r.error_signature[:60]}`" if r.error_signature else "-"
        lines.append(f"| {r.tier} | {r.name} | **{r.status}** | {r.duration_ms} | {cat} | {sig} |")

    if report.failed > 0:
        lines.extend(
            [
                "",
                "## Failure Diagnostics & Triage Breakdown",
                "",
            ]
        )
        for r in report.results:
            if r.status == "FAIL":
                lines.extend(
                    [
                        f"### [{r.tier}] {r.name} ({r.category})",
                        f"- **Command:** `{' '.join(r.command)}`",
                        f"- **Signature:** {r.error_signature}",
                        "```text",
                        (r.stdout + "\n" + r.stderr).strip()[-800:],
                        "```",
                        "",
                    ]
                )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Report written to %s and %s", md_path, json_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tiered tests with automated failure triage")
    parser.add_argument("--tier", choices=["1", "2", "3", "4", "no-mock", "mock", "e2e", "live", "all"], default="all")
    parser.add_argument("--fail-fast", action="store_true", help="Halt on first failure")
    args = parser.parse_args()

    py = sys.executable
    steps = get_tier_steps(args.tier, py)
    report = TriageReport(timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), total_steps=len(steps))

    for spec in steps:
        res = run_step(spec)
        report.results.append(res)
        if res.status == "PASS":
            report.passed += 1
        elif res.status == "SKIP":
            report.skipped += 1
        else:
            report.failed += 1
            if args.fail_fast:
                break

    artifacts_dir = REPO_ROOT / "artifacts"
    write_report(report, artifacts_dir)

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
