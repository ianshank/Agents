#!/usr/bin/env python3
"""Validation script for F-053 — matrix completeness: derived census, dim floors, artifact.

Checks:
    1. The generated coverage artifact exists and carries the GENERATED header.
    2. `python tests/test_matrix_coverage.py --check` exits 0 — the committed artifact
       matches an in-memory regeneration.
    3. **The policy itself holds**, evaluated here rather than inferred from check 2:
       every registered component meets its kind's dimension floor, the alias→canonical
       pairing equals the frozen map, and every censused kind appears in an M8 pipeline.
       An earlier version of this script claimed check 2 verified the floors
       "transitively"; it did not — `--check` compares document text, so `--update`
       followed by this validator would have reported PASS on a holed matrix whose doc
       faithfully recorded the holes. The CLI's `--update` now also refuses to write a
       holed artifact, closing the laundering path from the other side.
    4. No designated registry class parametrizes over constant literals (any nesting) —
       asserted via the guard library's own detector, imported rather than restated
       (the F-052 no-restatement principle; a second copy would recreate exactly the
       divergence this feature exists to prevent). Policy tables are structurally sound:
       every core registry kind has a floor, and the frozen alias map covers the same
       kinds; the live census holds exactly the expected kinds.
    5. `eval-harness-ci.yml` path filters include the generated artifact on BOTH the
       push and pull_request triggers, so a hand edit to the doc alone still runs the
       freshness gate (the F-052 reachability lesson, applied with F-052's own
       trigger-aware parser rather than a substring count).

Deterministic and offline: reads files, imports the guard library, and runs one local
subprocess (the guard CLI); no network.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS, _ROOT, os.path.join(_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_CI_WORKFLOW_REL = os.path.join(".github", "workflows", "eval-harness-ci.yml")

#: Deliberately RESTATED rather than imported from the guard library, unlike the
#: detector and policy tables below. Derived from ``mc.REQUIRED_DIMS`` this check would
#: read ``set(x) >= set(x)`` — a tautology, i.e. a dead check. As an independent anchor
#: it fails if someone deletes a kind's floor row, which is the point.
_CORE_KINDS = frozenset({"scorer", "judge", "dataset", "target", "sink"})

#: Must exceed the guard library's own ``_PROBE_TIMEOUT_SECONDS``: the CLI this bounds
#: spawns that census probe as a grandchild, so a tighter bound here would kill the
#: parent before the child could report.
_GUARD_CLI_TIMEOUT_SECONDS = 120


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # The guard library owns the artifact's location, the AST detector and the policy
    # tables; this validator imports all three rather than restating them (F-052's
    # no-restatement principle — a second copy recreates the divergence it exists to
    # prevent). The single exception is _CORE_KINDS; see its comment.
    from tests import _matrix_coverage as mc

    doc_path = str(mc.doc_path())
    doc_rel = os.path.relpath(doc_path, _ROOT)
    doc_rel_posix = doc_rel.replace(os.sep, "/")

    # 1. The artifact exists and is marked generated.
    doc_exists = os.path.exists(doc_path)
    _check(doc_exists, f"{doc_rel} exists", errors)
    if doc_exists:
        with open(doc_path, encoding="utf-8") as fh:
            first_line = fh.readline()
        _check(
            "GENERATED FILE" in first_line,
            f"{doc_rel} carries the GENERATED header on line 1",
            errors,
        )

    # 2. The guard CLI's freshness check passes (regenerate in memory, exact compare).
    completed = subprocess.run(
        [sys.executable, os.path.join("tests", "test_matrix_coverage.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=_GUARD_CLI_TIMEOUT_SECONDS,
    )
    # Both streams on failure: the CLI prints its staleness diff to stderr, which is
    # the whole diagnostic value of running it here.
    _check(
        completed.returncode == 0,
        "python tests/test_matrix_coverage.py --check exits 0"
        + (
            ""
            if completed.returncode == 0
            else f" (exit {completed.returncode}; stdout: {completed.stdout.strip()}; stderr: {completed.stderr.strip()})"
        ),
        errors,
    )

    # 3. The policy, evaluated here. Check 2 only proves the document matches a
    # regeneration — a holed matrix whose doc records the holes would satisfy it.
    census = mc.registry_census()
    classes = mc.extract_matrix_classes(mc.matrix_files())
    problems = mc.coverage_problems(census, classes)
    _check(
        not problems,
        "every registered component meets its kind's dimension floor"
        + ("" if not problems else f" — {len(problems)} violation(s): {problems}"),
        errors,
    )
    live_aliases = {kind: mc.census_aliases(census, kind) for kind in sorted(census)}
    _check(
        live_aliases == mc.FROZEN_ALIAS_MAP,
        "the alias->canonical pairing equals FROZEN_ALIAS_MAP exactly",
        errors,
    )
    from tests.test_matrix_eval_tools import PIPELINES

    unexercised = sorted(kind for kind, names in mc.pipeline_kinds(PIPELINES).items() if not names)
    _check(
        not unexercised,
        "every censused kind appears in at least one M8 pipeline"
        + ("" if not unexercised else f" — missing: {unexercised}"),
        errors,
    )
    # The census is read against an independent expectation, so a sixth registry
    # appearing (or a fifth disappearing) is caught here and not only in the suite.
    _check(
        set(census) == _CORE_KINDS,
        f"the live census holds exactly {sorted(_CORE_KINDS)} (got {sorted(census)})",
        errors,
    )

    # Every claimed cell must actually execute in CI: a class gated by importorskip on a
    # distribution the matrix job does not install is a false green in the artifact.
    with open(os.path.join(_ROOT, str(mc.MATRIX_CI_WORKFLOW)), encoding="utf-8") as fh:
        matrix_ci = fh.read()
    skip_problems = mc.skip_gate_problems(mc.matrix_files(), matrix_ci)
    _check(
        not skip_problems,
        "every skip-gated matrix class runs in CI" + ("" if not skip_problems else f" — {skip_problems}"),
        errors,
    )

    # 4. Detector and policy tables imported from the guard library.
    violations = mc.literal_parametrize_violations(mc.matrix_files())
    _check(
        not violations,
        "no designated registry class parametrizes over constant literals"
        + ("" if not violations else f": {violations}"),
        errors,
    )
    _check(
        set(mc.REQUIRED_DIMS) >= _CORE_KINDS,
        f"REQUIRED_DIMS covers every core registry kind {sorted(_CORE_KINDS)}",
        errors,
    )
    _check(
        set(mc.FROZEN_ALIAS_MAP) == set(mc.REQUIRED_DIMS),
        "FROZEN_ALIAS_MAP freezes the same kinds REQUIRED_DIMS floors",
        errors,
    )
    _check(
        all(reason.strip() for reason in mc.WAIVED.values()),
        "every waiver carries a non-empty reason",
        errors,
    )

    # 5. Reachability: a hand edit to the generated doc alone must still run the suite,
    # so the freshness gate can fail. Uses check_guard_reachability's trigger-aware
    # parser rather than a substring count: `text.count(path) >= 2` is satisfied by two
    # occurrences under the SAME trigger (or by a comment mentioning the path twice),
    # which is the weaker mechanism F-052 exists to have retired.
    import check_guard_reachability as reach

    with open(os.path.join(_ROOT, _CI_WORKFLOW_REL), encoding="utf-8") as fh:
        workflow = fh.read()
    pr_filters = reach.extract_path_filters(workflow)
    _check(
        any(reach.filter_matches(doc_rel_posix, glob) for glob in pr_filters),
        f"{_CI_WORKFLOW_REL} on.pull_request.paths selects {doc_rel_posix} (parsed {len(pr_filters)} filter(s))",
        errors,
    )
    # The push trigger is a separate list the same parser cannot reach (it keys off
    # `pull_request:`), so assert its membership textually within the push block only.
    push_block = workflow.split("push:", 1)[-1].split("pull_request:", 1)[0]
    _check(
        doc_rel_posix in push_block,
        f"{_CI_WORKFLOW_REL} on.push.paths lists {doc_rel_posix}",
        errors,
    )

    return report(logger, "F-053", errors)


if __name__ == "__main__":
    raise SystemExit(main())
