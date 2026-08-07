#!/usr/bin/env python3
"""Validation script for F-052 - Protected-path guard reachability.

Checks:
    1. Every ``PROTECTED_PATTERNS`` entry is reachable via the guard workflow's
       ``on.pull_request.paths`` filter.
    2. The check FAILS when a covering filter is removed (mutation). A reachability
       guard that stops detecting drift is worse than none, because the green tick is
       read as evidence.
    3. ``PROTECTED_PATTERNS`` is imported, not restated, and glob matching reuses
       ``eval_protected_paths._glob_to_regex`` — so the checker cannot disagree with the
       guard it audits.
    4. Path-boundary semantics hold (``tests/**`` vs ``testsuite/``; ``.github/workflows/**``
       vs ``.github/CODEOWNERS``).
    5. Filters under other triggers (push/schedule) are not counted as pull_request coverage.
    6. ``--json`` output is byte-stable for a given input.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

#: Patterns whose loss of coverage would be most damaging, used for the mutation checks.
_MUTATION_TARGETS = ("architecture.yaml", "config/**", "agent-core/tests/**", ".github/**")


def main() -> int:
    configure_logging()
    errors: list[str] = []

    import inspect
    import json
    import pathlib
    import tempfile

    import check_guard_reachability as gr
    import eval_protected_paths as epp

    repo_root = pathlib.Path(_SCRIPTS).parent

    # 1. every protected pattern is reachable today
    coverages, _filters = gr.analyse(repo_root)
    unreachable = [c.pattern for c in coverages if not c.reachable]
    _check(
        not unreachable,
        f"every protected pattern is reachable by the guard (unreachable: {unreachable})",
        errors,
    )
    _check(
        {c.pattern for c in coverages} == set(epp.PROTECTED_PATTERNS),
        "every PROTECTED_PATTERNS entry is accounted for in the report",
        errors,
    )

    # 2. mutation: removing a covering filter must fail the check
    workflow_rel = gr.GUARD_WORKFLOW
    original = (repo_root / workflow_rel).read_text(encoding="utf-8")

    def _analyse_text(text: str) -> list[str] | str:
        """Unreachable patterns for a mutated workflow, or the guard-not-invoked message."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / workflow_rel.parent).mkdir(parents=True)
            (root / workflow_rel).write_text(text, encoding="utf-8")
            try:
                cov, _ = gr.analyse(root)
            except gr.GuardNotInvokedError as exc:
                return str(exc)
            return [c.pattern for c in cov if not c.reachable]

    # 2a. NARROWING a filter to a child of the protected tree must also fail. A single
    # representative probe made `config/sample/**` look like coverage for `config/**`,
    # while a PR touching config/other.yaml ran no guard — a false green.
    narrowed = _analyse_text(original.replace('- "config/**"', '- "config/sample/**"'))
    _check(
        isinstance(narrowed, list) and "config/**" in narrowed,
        f"a child-only filter (config/sample/**) does not count as covering config/** (got {narrowed})",
        errors,
    )

    # 2b. The guard must be INVOKED, not merely mentioned. With the job deleted and a
    # broad filter left in place, every pattern still looks reachable.
    removed = _analyse_text("\n".join(x for x in original.splitlines() if gr.GUARD_SCRIPT not in x))
    _check(
        isinstance(removed, str) and "does not run" in removed,
        f"deleting the guard invocation fails closed rather than reporting OK (got {removed})",
        errors,
    )
    commented = _analyse_text(
        original.replace(
            "      - run: python scripts/check_protected_changes.py",
            "      # - run: python scripts/check_protected_changes.py",
        )
    )
    _check(
        isinstance(commented, str) and "does not run" in commented,
        f"a commented-out guard invocation does not satisfy the check (got {commented})",
        errors,
    )

    for target in _MUTATION_TARGETS:
        mutated = "\n".join(line for line in original.splitlines() if line.strip() != f'- "{target}"')
        if mutated == original:
            _check(False, f"mutation target {target!r} was not present to remove", errors)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / workflow_rel.parent).mkdir(parents=True)
            (root / workflow_rel).write_text(mutated + "\n", encoding="utf-8")
            mutated_cov, _ = gr.analyse(root)
            still_unreachable = [c.pattern for c in mutated_cov if not c.reachable]
            _check(
                target in still_unreachable,
                f"removing the {target!r} filter makes the check report it unreachable",
                errors,
            )

    # 3. single-sourcing: the checker must not restate the list or reimplement globbing
    source = inspect.getsource(gr)
    _check(
        "PROTECTED_PATTERNS" in source and "from eval_protected_paths import" in source,
        "check_guard_reachability imports PROTECTED_PATTERNS rather than restating it",
        errors,
    )
    _check(
        "_glob_to_regex" in source,
        "glob matching reuses eval_protected_paths._glob_to_regex",
        errors,
    )
    # A literal re-declaration would look like `PROTECTED_PATTERNS = (` in this module.
    _check(
        "PROTECTED_PATTERNS = (" not in source,
        "the pattern list is not duplicated inside the checker",
        errors,
    )

    # 4. path-boundary semantics
    for path, glob, expected in (
        ("tests/test_x.py", "tests/**", True),
        ("testsuite/x.py", "tests/**", False),
        (".github/CODEOWNERS", ".github/**", True),
        (".github/CODEOWNERS", ".github/workflows/**", False),
    ):
        _check(
            gr.filter_matches(path, glob) is expected,
            f"filter_matches({path!r}, {glob!r}) is {expected}",
            errors,
        )

    # 5. other triggers must not be counted as pull_request coverage
    sample = (
        "on:\n"
        "  push:\n"
        "    paths:\n"
        '      - "should-not-count/**"\n'
        "  pull_request:\n"
        "    paths:\n"
        '      - "counted/**"\n'
        "  workflow_dispatch:\n"
        "\njobs:\n  x: {}\n"
    )
    _check(
        gr.extract_path_filters(sample) == ["counted/**"],
        "push-trigger filters are not counted as pull_request coverage",
        errors,
    )

    # 6. byte-stable json
    import contextlib
    import io

    def _json_run() -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gr.main(["--repo", str(repo_root), "--json"])
        return buf.getvalue()

    first, second = _json_run(), _json_run()
    _check(first == second, "--json output is byte-stable across runs", errors)
    _check(json.loads(first)["passed"] is True, "--json reports the repo as passing", errors)

    # The gate must stay wired into CI; check_charter_invariants owns that assertion.
    invariants = (repo_root / "scripts" / "check_charter_invariants.py").read_text(encoding="utf-8")
    _check(
        "check_guard_reachability.py" in invariants,
        "the gate is registered in check_charter_invariants._EXPECTED_GATE_SCRIPTS",
        errors,
    )

    return report(logger, "F-052", errors)


if __name__ == "__main__":
    sys.exit(main())
