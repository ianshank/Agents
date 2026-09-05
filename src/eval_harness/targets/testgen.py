"""Suite-execution target: run a generated test suite and report structured evidence.

Implements ``openspec/changes/add-testgen-eval-matrix`` task 2. This is a **callable
target**, not a registered ``TargetRunner``: it is named from configuration as
``eval_harness.targets.testgen:run_generated_suite`` and is therefore gated by the
deny-by-default callable allowlist (ADR 0039). Executing model-authored test code is the
highest-privilege operation in this capability, and it uses the mechanism the repository
already built for that class of risk rather than an exemption for being convenient.

The seam this file exists to hold: **the target executes, the scorers only read.** Every
scorer in ``scorers/test_generation/`` is a pure function of the payload built here, so
they stay deterministic under ``repetitions > 1``, run in the offline suite unchanged, and
are cheap to matrix-cover. Moving execution into a scorer would break all three.

Why a subprocess, in a package that had none: a wall-clock limit is unenforceable
in-process. A generated test containing an unbounded loop would hang the harness, and no
`signal`-based timeout is portable or safe mid-run. ``_suite_runner.py`` is the only code
that touches model-authored input, and it runs in its own interpreter with its own working
directory.

Two evidence definitions are worth stating because both could have been fudged:

**Covered** means the suite actually drove inputs at which the mutant differs. ``focal.py``
is instrumented to record its call arguments, so "of what it reached" is measured rather
than assumed. Without this the normalized denominator would have to be guessed, and the
spec requires the payload to name what each figure was computed from.

**Killed** means a test that passed against the reference fails against the mutant. Not
"any test fails" — a suite that is red on correct code would otherwise appear to kill every
mutant it was already failing on, turning a false-alarm defect into a high mutation score.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..core.types import TESTGEN_EVIDENCE_KEY, TargetOutput
from . import _suite_runner

logger = logging.getLogger(__name__)

#: Re-exported from ``core.types`` so a reader of this module finds the key where they
#: expect it. Defined there, not here: the scorers read it too, and importing it from this
#: module gave them a ``scorers -> targets`` component edge.
EVIDENCE_KEY = TESTGEN_EVIDENCE_KEY

#: Default wall-clock limit per suite execution, in seconds. Overridable per item, because
#: an item with forty mutants legitimately needs longer than one with two. A timeout is
#: recorded as evidence, never raised: raising would abort the whole run under the default
#: item-error policy (ADR 0038), turning one slow suite into zero measurements.
DEFAULT_TIMEOUT_SECONDS = 30.0

#: Instrumentation appended to every focal implementation before it is written into the
#: sandbox. Records the arguments the suite drives, which is what makes "covered" a
#: measurement. Kept as a template rather than assembled inline so the generated file
#: stays readable when a failure needs debugging.
_RECORDER_TEMPLATE = """

__calls__ = []
_focal_undecorated = {name}


def {name}(*args, **kwargs):
    __calls__.append([list(args), dict(sorted(kwargs.items()))])
    return _focal_undecorated(*args, **kwargs)
"""


def _write_sandbox(workdir: Path, implementation: str, focal_name: str, suite: str) -> None:
    """Materialise one execution sandbox: an instrumented focal module and the suite."""
    (workdir / _suite_runner.FOCAL_FILENAME).write_text(
        implementation + _RECORDER_TEMPLATE.format(name=focal_name), encoding="utf-8"
    )
    (workdir / _suite_runner.SUITE_FILENAME).write_text(suite, encoding="utf-8")


def _execute(workdir: Path, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    """Run the sandbox, returning ``(payload, failure)`` with exactly one of them set."""
    runner = Path(_suite_runner.__file__)
    try:
        completed = subprocess.run(
            [sys.executable, str(runner), str(workdir)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workdir),
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if completed.returncode != 0:
        return None, f"runner exited {completed.returncode}: {completed.stderr.strip()[:200]}"
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"runner emitted unparseable output: {exc}"


def _run_against(
    root: Path, label: str, implementation: str, focal_name: str, suite: str, timeout: float
) -> tuple[dict[str, Any] | None, str | None]:
    """One sandboxed execution in its own subdirectory, so runs cannot see each other."""
    workdir = root / label
    workdir.mkdir(parents=True, exist_ok=True)
    _write_sandbox(workdir, implementation, focal_name, suite)
    return _execute(workdir, timeout)


def _covered(mutant: dict[str, Any], called: set[tuple[int, ...]], grid: list[list[int]]) -> bool:
    """Whether the suite drove any input at which *mutant* differs from the reference."""
    differs = mutant.get("differs_at")
    if differs is None:
        # A corpus that does not publish differing indices cannot support the normalized
        # denominator. Counting the mutant as covered anyway would inflate it silently.
        return False
    return any(tuple(grid[i]) in called for i in differs if i < len(grid))


def _called_inputs(payload: dict[str, Any]) -> set[tuple[int, ...]]:
    """Positional call arguments the suite drove, as hashable tuples."""
    called: set[tuple[int, ...]] = set()
    for args, _kwargs in payload.get("calls", []):
        try:
            called.add(tuple(args))
        except TypeError:  # an unhashable argument is not a grid point
            continue
    return called


def run_generated_suite(inputs: dict[str, Any]) -> TargetOutput:
    """Execute ``inputs['suite']`` against the reference and every non-equivalent mutant.

    Returns a ``TargetOutput`` whose ``metadata[EVIDENCE_KEY]`` carries the payload the
    four scorers read. Per-item failures are reported as ``error`` plus whatever evidence
    was gathered, never raised: a raise aborts the whole run under the default item-error
    policy, which would turn one unrunnable suite into zero measurements for every item.
    """
    suite = inputs.get("suite")
    reference = inputs.get("reference")
    focal_name = inputs.get("focal_name")
    if not (suite and reference and focal_name):
        return TargetOutput(output=None, error="item is missing suite, reference or focal_name")

    mutants: list[dict[str, Any]] = list(inputs.get("mutants") or [])
    obligations: list[dict[str, Any]] = list(inputs.get("obligations") or [])
    grid: list[list[int]] = [list(point) for point in inputs.get("grid") or []]
    timeout = float(inputs.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)

    with tempfile.TemporaryDirectory(prefix="eval-harness-testgen-") as tmp:
        root = Path(tmp)
        baseline, failure = _run_against(root, "reference", reference, focal_name, suite, timeout)
        if baseline is None:
            evidence = _empty_evidence(mutants, timed_out=failure == "timeout")
            logger.warning("testgen: reference run failed for %s: %s", focal_name, failure)
            return TargetOutput(output=None, error=failure, metadata={EVIDENCE_KEY: evidence})

        evidence = _baseline_evidence(baseline, mutants)
        if baseline["collected"] == 0:
            # Non-executable: the spec makes the other three scorers not-applicable here,
            # so running 40 mutants against a suite that never collected buys nothing.
            return TargetOutput(output=evidence, metadata={EVIDENCE_KEY: evidence})

        called = _called_inputs(baseline)
        survivors = set(baseline["passed"])
        killed_ids: list[str] = []
        covered = 0
        for mutant in mutants:
            if mutant.get("equivalent"):
                continue
            if _covered(mutant, called, grid):
                covered += 1
            result, mutant_failure = _run_against(
                root, f"mutant-{mutant['id']}", mutant["source"], focal_name, suite, timeout
            )
            if mutant_failure == "timeout":
                evidence["timed_out"] = True
                continue
            if result is None:
                continue
            # Killed = a test that PASSED on the reference now fails. "Any failure" would
            # let a suite that is red on correct code claim every mutant it already failed.
            if survivors & set(result["failed"]):
                killed_ids.append(mutant["id"])

        evidence["mutants"]["covered"] = covered
        evidence["mutants"]["killed"] = len(killed_ids)
        evidence["obligations_covered"] = sorted(
            ob["id"] for ob in obligations if ob.get("witness_mutant") in set(killed_ids)
        )
        evidence["obligations_declared"] = [ob["id"] for ob in obligations]
        return TargetOutput(output=evidence, metadata={EVIDENCE_KEY: evidence})


def _baseline_evidence(baseline: dict[str, Any], mutants: list[dict[str, Any]]) -> dict[str, Any]:
    """The payload shape, filled in as far as the reference run alone can."""
    non_equivalent = [m for m in mutants if not m.get("equivalent")]
    return {
        "collected": baseline["collected"],
        "collection_error": baseline["collection_error"],
        "green_on_correct": {
            "ran": baseline["collected"],
            "failed": len(baseline["failed"]),
        },
        "mutants": {
            "generated": len(non_equivalent),
            "equivalent_excluded": len(mutants) - len(non_equivalent),
            "covered": 0,
            "killed": 0,
        },
        "obligations_covered": [],
        "obligations_declared": [],
        "timed_out": False,
    }


def _empty_evidence(mutants: list[dict[str, Any]], *, timed_out: bool) -> dict[str, Any]:
    """Evidence for a run that never produced a reference result."""
    non_equivalent = [m for m in mutants if not m.get("equivalent")]
    return {
        "collected": 0,
        "collection_error": "reference run did not complete",
        "green_on_correct": {"ran": 0, "failed": 0},
        "mutants": {
            "generated": len(non_equivalent),
            "equivalent_excluded": len(mutants) - len(non_equivalent),
            "covered": 0,
            "killed": 0,
        },
        "obligations_covered": [],
        "obligations_declared": [],
        "timed_out": timed_out,
    }
