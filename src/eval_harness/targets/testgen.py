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
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass
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

#: How much of a runner traceback to keep in the reported error. Bounded because the string
#: reaches ``TargetOutput.error`` and from there a results file a human reads.
_RUNNER_ERROR_CHARS = 200

#: The failure string :func:`_execute` returns when the wall-clock limit fired, named
#: rather than repeated: three call sites compare against it, and a typo in any of them
#: would fail *open* — recording a timeout as a generic error and leaving ``timed_out``
#: false, which is the one distinction a soak needs from this field.
TIMEOUT_FAILURE = "timeout"

#: How many mutant-run failures to keep in the evidence. Bounded for the same reason as
#: ``_RUNNER_ERROR_CHARS``: this list is serialised into a results file.
_MAX_RECORDED_MUTANT_ERRORS = 20

#: Sandbox subdirectory names. Both reach a filesystem path, a log line and any debugging
#: session, so they are named here rather than spelled inline at their two call sites.
_REFERENCE_LABEL = "reference"
_MUTANT_LABEL_PREFIX = "mutant-"

#: How much of a mutant id to keep in its sandbox directory name. Bounded because the id is
#: corpus data and a path component has an OS-imposed length limit; uniqueness comes from
#: the index that precedes it, not from the id.
_MAX_LABEL_CHARS = 40

#: Instrumentation appended to every focal implementation before it is written into the
#: sandbox. Records the arguments the suite drives, which is what makes "covered" a
#: measurement. Kept as a template rather than assembled inline so the generated file
#: stays readable when a failure needs debugging.
#:
#: Arguments are **bound to the focal signature** before being recorded, so
#: ``add(n=2, k=1)`` and ``add(2, 1)`` record the same grid point. Recording raw
#: ``args`` alone made a keyword call — entirely idiomatic in a generated suite — look like
#: a call with no arguments, so the mutant it reached was scored uncovered while still
#: being killed. That produced a *normalized mutation score above 1.0*, verified end to end
#: at 2.0 before this fix. Binding fails only for a call the focal method would reject
#: anyway; the raw form is kept for that case so the evidence still shows what was tried.
_RECORDER_TEMPLATE = """

import inspect as _inspect

__calls__ = []
_focal_undecorated = {name}
_focal_signature = _inspect.signature(_focal_undecorated)


def {name}(*args, **kwargs):
    try:
        _bound = _focal_signature.bind(*args, **kwargs)
        _bound.apply_defaults()
        __calls__.append([list(_bound.arguments.values()), {{}}])
    except TypeError:
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
    """Run the sandbox, returning ``(payload, failure)`` with exactly one of them set.

    The sandbox's own stdout and stderr are DISCARDED, and the verdict is read from a file
    the runner writes. Two reasons, one correctness and one resource:

    A generated test calling ``print()`` is completely ordinary. An earlier cut of this
    read the verdict from stdout, so any suite that printed corrupted the JSON and was
    scored NON-EXECUTABLE — a good suite failing for writing to a channel it had every
    right to write to. Verified against this checkout before the fix.

    And a suite printing in a loop would otherwise be buffered into the harness's address
    space by ``capture_output=True``, with no bound. ``DEVNULL`` removes that path.
    """
    runner = Path(_suite_runner.__file__)
    try:
        completed = subprocess.run(
            [sys.executable, str(runner), str(workdir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            cwd=str(workdir),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, TIMEOUT_FAILURE

    result_path = workdir / _suite_runner.RESULT_FILENAME
    if result_path.exists():
        try:
            payload: dict[str, Any] = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"runner emitted unparseable output: {exc}"
        return payload, None

    detail = _runner_error(workdir)
    return None, f"runner exited {completed.returncode}: {detail}"


def _runner_error(workdir: Path) -> str:
    """The runner's own traceback, truncated, or a note that it left none."""
    error_path = workdir / _suite_runner.RUNNER_ERROR_FILENAME
    try:
        return error_path.read_text(encoding="utf-8").strip()[-_RUNNER_ERROR_CHARS:] or "no detail"
    except OSError:
        return "no detail"


def _run_against(
    root: Path, label: str, implementation: str, focal_name: str, suite: str, timeout: float
) -> tuple[dict[str, Any] | None, str | None]:
    """One sandboxed execution in its own subdirectory, so runs cannot see each other.

    The subdirectory is asserted to be *inside* ``root``. Callers already pass a sanitised
    label (see :func:`_sandbox_label`), so this is defence in depth rather than the primary
    guard — but it is the last line before a write, and a path escape here writes
    model-supplied bytes to an attacker-chosen location.
    """
    workdir = root / label
    resolved_root = root.resolve()
    if not workdir.resolve().is_relative_to(resolved_root):
        raise ValueError(f"sandbox label {label!r} escapes the execution root")
    workdir.mkdir(parents=True, exist_ok=True)
    _write_sandbox(workdir, implementation, focal_name, suite)
    return _execute(workdir, timeout)


def _sandbox_label(index: int, mutant_id: Any) -> str:
    """A filesystem-safe, collision-free directory name for one mutant's sandbox.

    ``mutant['id']`` comes from a corpus file, which is **data**, and it used to be
    interpolated into a path directly. Verified against this checkout before the fix: an id
    of ``../../../../ESCAPED`` wrote ``focal.py`` outside the execution root entirely.
    Corpora in this repository are generated and reviewed, but a target whose safety rests
    on the goodwill of its input is not safe — and this is the one target that writes
    model-adjacent code to disk and executes it.

    The index is kept in the name for a second reason found by the same audit: two mutants
    sharing an id would otherwise share a directory, so the second would overwrite the
    first's sandbox and both could be credited from one run.
    """
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(mutant_id))
    return f"{_MUTANT_LABEL_PREFIX}{index:03d}-{safe[:_MAX_LABEL_CHARS]}"


def _resolve_timeout(raw: Any) -> tuple[float, str | None]:
    """``(seconds, problem)`` for an item's ``timeout_seconds``, never raising.

    ``float(inputs.get("timeout_seconds") or DEFAULT)`` accepted anything and raised
    ``ValueError`` on a non-numeric value — straight out of a target whose documented
    contract is that a per-item failure is reported, never raised, because a raise aborts
    the whole run under the default item-error policy (ADR 0038). One malformed item became
    zero measurements for every other item.

    ``0`` and ``None`` mean "unset" and take the default, matching the previous ``or``
    behaviour. A negative value fired ``TimeoutExpired`` in under a millisecond, recording a
    fabricated timeout over a suite nothing had run; ``nan`` and ``inf`` disable the limit
    that is the whole reason this target uses a subprocess. All three are now refused with a
    reason the results file carries.
    """
    if raw is None or raw is False or raw == 0:
        return DEFAULT_TIMEOUT_SECONDS, None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS, f"timeout_seconds must be a number, got {raw!r}"
    if not math.isfinite(seconds) or seconds <= 0:
        return DEFAULT_TIMEOUT_SECONDS, f"timeout_seconds must be finite and positive, got {raw!r}"
    return seconds, None


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
    timeout, timeout_problem = _resolve_timeout(inputs.get("timeout_seconds"))
    if timeout_problem is not None:
        logger.warning("testgen: %s for %s", timeout_problem, focal_name)
        return TargetOutput(
            output=None,
            error=timeout_problem,
            metadata={EVIDENCE_KEY: _empty_evidence(mutants, timed_out=False)},
        )

    with tempfile.TemporaryDirectory(prefix="eval-harness-testgen-") as tmp:
        root = Path(tmp)
        baseline, failure = _run_against(root, _REFERENCE_LABEL, reference, focal_name, suite, timeout)
        if baseline is None:
            evidence = _empty_evidence(mutants, timed_out=failure == TIMEOUT_FAILURE)
            logger.warning("testgen: reference run failed for %s: %s", focal_name, failure)
            return TargetOutput(output=None, error=failure, metadata={EVIDENCE_KEY: evidence})

        evidence = _baseline_evidence(baseline, mutants)
        if baseline["collected"] == 0:
            # Non-executable: the spec makes the other three scorers not-applicable here,
            # so running 40 mutants against a suite that never collected buys nothing.
            return TargetOutput(output=evidence, metadata={EVIDENCE_KEY: evidence})

        outcome = _run_mutants(
            root=root,
            mutants=mutants,
            focal_name=focal_name,
            suite=suite,
            timeout=timeout,
            called=_called_inputs(baseline),
            survivors=set(baseline["passed"]),
            grid=grid,
        )
        evidence["mutants"]["covered"] = outcome.covered
        evidence["mutants"]["killed"] = len(outcome.killed_ids)
        evidence["mutants"]["errored"] = len(outcome.errors)
        evidence["mutant_errors"] = outcome.errors
        evidence["timed_out"] = outcome.timed_out
        witnessed = set(outcome.killed_ids)
        # De-duplicated against the declared set: an obligation declared once and witnessed
        # by two killed mutants must not count twice, which is how recall reached 2.0.
        evidence["obligations_covered"] = sorted(
            {ob["id"] for ob in obligations if ob.get("witness_mutant") in witnessed}
        )
        evidence["obligations_declared"] = [ob["id"] for ob in obligations]
        return TargetOutput(output=evidence, metadata={EVIDENCE_KEY: evidence})


@dataclass(frozen=True)
class _MutantOutcome:
    """What the mutant sweep observed. A record rather than four parallel locals, so the
    invariant that binds them — ``killed <= covered`` — is stated in one place."""

    covered: int
    killed_ids: list[str]
    errors: list[dict[str, str]]
    timed_out: bool


def _run_mutants(
    *,
    root: Path,
    mutants: list[dict[str, Any]],
    focal_name: str,
    suite: str,
    timeout: float,
    called: set[tuple[int, ...]],
    survivors: set[str],
    grid: list[list[int]],
) -> _MutantOutcome:
    """Run the suite against every non-equivalent mutant and tally what happened."""
    killed_ids: list[str] = []
    errors: list[dict[str, str]] = []
    covered = 0
    timed_out = False
    for index, mutant in enumerate(mutants):
        if mutant.get("equivalent"):
            continue
        result, failure = _run_against(
            root, _sandbox_label(index, mutant.get("id")), mutant["source"], focal_name, suite, timeout
        )
        # Killed = a test that PASSED on the reference now fails. "Any failure" would let a
        # suite that is red on correct code claim every mutant it already failed.
        killed = result is not None and bool(survivors & set(result["failed"]))
        if killed:
            killed_ids.append(mutant["id"])
        # A killed mutant is covered BY CONSTRUCTION: a suite cannot make a mutant fail
        # without driving an input at which the mutant differs. Counting it here rather than
        # trusting `differs_at` alone is what keeps `killed <= covered`, and with it the
        # normalized denominator inside [0, 1]. A corpus that under-declares `differs_at`
        # used to produce a score above 1.0 rather than a visible defect.
        if killed or _covered(mutant, called, grid):
            covered += 1
        if failure is not None:
            # A mutant that never ran cannot be killed, so it depresses BOTH denominators.
            # Recording it keeps an infrastructure failure legible in the results file
            # instead of arriving as a low mutation score.
            logger.warning("testgen: mutant %s failed for %s: %s", mutant["id"], focal_name, failure)
            if len(errors) < _MAX_RECORDED_MUTANT_ERRORS:
                errors.append({"id": str(mutant["id"]), "reason": failure})
            timed_out = timed_out or failure == TIMEOUT_FAILURE
    return _MutantOutcome(covered=covered, killed_ids=killed_ids, errors=errors, timed_out=timed_out)


def _baseline_evidence(baseline: dict[str, Any], mutants: list[dict[str, Any]]) -> dict[str, Any]:
    """The payload shape, filled in as far as the reference run alone can."""
    non_equivalent = [m for m in mutants if not m.get("equivalent")]
    return {
        "collected": baseline["collected"],
        "collection_error": baseline["collection_error"],
        "green_on_correct": {
            "ran": baseline["collected"],
            "failed": len(baseline["failed"]),
            # The exception behind each false alarm, from the reference run only. A mutant
            # run's failures are the point of the exercise; a failure against the KNOWN-
            # CORRECT implementation is a defect in the suite, and this is the only place
            # a reader can find out what it was.
            "failures": dict(baseline.get("failures") or {}),
        },
        "mutants": {
            "generated": len(non_equivalent),
            "equivalent_excluded": len(mutants) - len(non_equivalent),
            "covered": 0,
            "killed": 0,
            "errored": 0,
        },
        "mutant_errors": [],
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
        "green_on_correct": {"ran": 0, "failed": 0, "failures": {}},
        "mutants": {
            "generated": len(non_equivalent),
            "equivalent_excluded": len(mutants) - len(non_equivalent),
            "covered": 0,
            "killed": 0,
            "errored": 0,
        },
        "mutant_errors": [],
        "obligations_covered": [],
        "obligations_declared": [],
        "timed_out": timed_out,
    }
