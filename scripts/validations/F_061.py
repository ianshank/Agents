#!/usr/bin/env python3
"""Validation script for F-061 — added tests no longer carry the protected-path penalty.

Behavioural, deterministic and offline: loads the committed proxy config and exercises
``agent_confidence.compute_confidence`` directly. Nothing here reads the outcome store, the
network, or git.

The property this pins has two halves, and both are load-bearing:

    1. An ADDED test raises the score. Every ``tests/**`` root is eval-protected, so before
       F-061 a test file was priced twice (``+w_tests * test_ratio`` and ``-w_protected``)
       and adding tests lowered confidence.
    2. A MODIFIED test still carries the penalty. Withholding *all* tests would make
       "modify only an eval-defining test" the highest-confidence class in the system --
       the Goodhart failure ``scripts/fix_loop.py`` exists to name. Half a fix is worse
       than none here, so the gate asserts the second half explicitly.

Plus the backwards-compatibility contract: ``added=None`` reproduces the pre-F-061 result,
which is what lets stored records and non-supplying callers stay valid.

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
from _common import check as _check
from _common import configure_logging, report
from check_protected_changes import ConfigError

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)
_PROXY = os.path.join(_ROOT, "config", "agent-confidence.yaml")
_SEED_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "merge-gate-seed.yml")

# Representative changes. Paths are chosen so `tests/test_a.py` is BOTH a configured test
# glob and an eval-protected path -- the overlap that produced the defect.
_SRC = "src/eval_harness/x.py"
_TEST = "tests/test_x.py"
_LINES = 100


def _validate_behaviour(errors: list[str]) -> None:
    try:
        cfg = ac.ProxyConfig.load(_PROXY)
    except ConfigError as exc:
        _check(False, f"committed proxy config loads ({exc})", errors)
        return

    with_test = [_SRC, _TEST]
    no_test = [_SRC, "src/eval_harness/y.py"]

    added = ac.compute_confidence(with_test, _LINES, cfg, added=[_TEST])
    legacy = ac.compute_confidence(with_test, _LINES, cfg)
    baseline = ac.compute_confidence(no_test, _LINES, cfg)
    modified = ac.compute_confidence(with_test, _LINES, cfg, added=[])

    _check(
        added > legacy,
        f"an ADDED test raises the score ({added} > {legacy})",
        errors,
    )
    _check(
        added > baseline,
        f"adding a test beats not adding one ({added} > {baseline})",
        errors,
    )
    _check(
        modified == legacy,
        f"a MODIFIED test still carries the protected penalty ({modified} == {legacy})",
        errors,
    )
    _check(
        ac.compute_confidence(with_test, _LINES, cfg, added=None) == legacy,
        "added=None reproduces the pre-F-061 result (backwards-compatibility contract)",
        errors,
    )
    # An added *non-test* protected file must NOT dodge the penalty -- only tests are withheld.
    protected_non_test = ["config/agent-confidence.yaml"]
    _check(
        ac.compute_confidence(protected_non_test, 20, cfg, added=protected_non_test)
        == ac.compute_confidence(protected_non_test, 20, cfg),
        "an added non-test protected file still carries the penalty",
        errors,
    )


def _validate_wiring(errors: list[str]) -> None:
    """The seed path must actually supply the added set, or the fix is inert in production."""
    try:
        with open(_SEED_WORKFLOW, encoding="utf-8") as fh:
            wf = fh.read()
    except OSError as exc:
        _check(False, f"seed workflow readable ({exc})", errors)
        return
    for needle, why in [
        ("--diff-filter=A", "seed workflow derives the added-file set from git"),
        ("added_files.z", "the added set is written to its own NUL-delimited file"),
        ("--added-from", "agent_confidence.py is invoked with the added set"),
    ]:
        _check(needle in wf, f"seed workflow: {why}", errors)


def validate_f061() -> int:
    configure_logging()
    errors: list[str] = []
    _validate_behaviour(errors)
    _validate_wiring(errors)
    return report(logger, "F-061", errors)


def main() -> int:
    return validate_f061()


if __name__ == "__main__":
    sys.exit(main())
