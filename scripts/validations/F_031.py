#!/usr/bin/env python3
"""Validation script for F-031 - Operational-scripts quality gates.

Asserts the 2026-07 gap-analysis remediation stays enforced (see
docs/gap-analysis-2026-07.md):
    1. eval-harness CI lints, format-checks, and type-checks ``scripts/``.
    2. eval-harness CI runs the operational-scripts coverage gate.

       Checks 1/2 assert the *guarantee* (the step runs in eval-harness CI), not one
       wiring of it: they pass whether the step is inline in the workflow or delegated to
       the generated ``scripts/quality-gate.sh`` (ADR 0021). Pinning the inline spelling
       silently broke this gate the moment the delegation landed, while the guarantee was
       intact. Because the delegated gate lints the whole tree rather than naming
       ``scripts``, check 1 additionally guards the one way delegation could weaken it --
       a root ruff ``exclude``.
    3. ``scripts/.coveragerc`` gates at >=85 and excludes ``validations/``
       (the F_* files are themselves one-shot CI gates, not unit-test targets).
    4. The previously-untested operational scripts have dedicated test files.
    5. The ruff per-file-ignores stay scoped to the three deliberate patterns
       (bootstrap E402, feature-ID N999, docstring typography RUF00x) - no
       blanket exemptions.
    6. ``mypy scripts`` resolution config keeps ``scripts/validations`` on
       ``mypy_path`` (as a bare string or one entry of a list), so the type gate
       cannot silently regress to unresolvable ``_common`` imports.

Deterministic and offline: reads config/workflow files only, runs nothing.

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import configparser
import logging
import os
import re
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


def _read(rel_path: str) -> str:
    with open(os.path.join(_ROOT, rel_path), encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1./2. CI enforcement, either inline in the workflow or via the delegated gate.
    ci = _read(os.path.join(".github", "workflows", "eval-harness-ci.yml"))
    gate = _read(os.path.join("scripts", "quality-gate.sh"))
    _check(
        ci_enforces(ci, gate, inline="ruff check src tests scripts", in_gate='ruff check "."'),
        "CI lints scripts/",
        errors,
    )
    _check(
        ci_enforces(ci, gate, inline="ruff format --check src tests scripts", in_gate='ruff format --check "."'),
        "CI format-checks scripts/",
        errors,
    )
    _check(
        ci_enforces(ci, gate, inline="mypy scripts", in_gate='mypy "scripts"'),
        "CI type-checks scripts/",
        errors,
    )
    _check(
        ci_enforces(
            ci,
            gate,
            inline="--cov=scripts --cov-config=scripts/.coveragerc",
            in_gate="--cov=scripts --cov-config=scripts/.coveragerc",
        ),
        "CI runs the operational-scripts coverage gate",
        errors,
    )
    # The delegated gate lints the whole tree (``ruff check "."``) rather than naming
    # ``scripts`` explicitly, so an ``exclude`` entry in the root ruff config would drop
    # scripts/ from the lint while the checks above still passed. Guard the escape hatch:
    # this is the one way delegation could weaken F-031's lint guarantee.
    pyproject = _read("pyproject.toml")
    ruff_exclude = re.search(r"^\[tool\.ruff\](?P<body>.*?)(?=^\[)", pyproject, re.DOTALL | re.MULTILINE)
    _check(
        ruff_exclude is None or "exclude" not in ruff_exclude.group("body"),
        "root ruff config does not exclude paths (whole-tree lint still covers scripts/)",
        errors,
    )

    # 3. Coverage gate config: >=85, branch measurement, validations excluded.
    cov = configparser.ConfigParser()
    cov.read(os.path.join(_ROOT, "scripts", ".coveragerc"))
    fail_under = cov.getfloat("report", "fail_under", fallback=0.0)
    _check(fail_under >= 85.0, f"scripts coverage gate fail_under={fail_under} >= 85", errors)
    _check(
        cov.getboolean("run", "branch", fallback=False),
        "scripts coverage gate measures branches",
        errors,
    )
    _check(
        "validations" in cov.get("run", "omit", fallback=""),
        "scripts coverage gate excludes validations/ (self-executing gates)",
        errors,
    )

    # 4. The formerly-untested operational scripts keep dedicated test files.
    for test_file in (
        "tests/test_validate_script.py",
        "tests/test_select_next_script.py",
        "tests/test_init_script.py",
    ):
        _check(os.path.exists(os.path.join(_ROOT, test_file)), f"{test_file} exists", errors)

    # 5./6. Lint/type scoping stays deliberate and documented in pyproject (read above).
    _check(
        '"scripts/validations/*.py" = ["E402", "N999"]' in pyproject,
        "per-file-ignores scoped to validations bootstrap/naming only",
        errors,
    )
    _check(
        '"scripts/**" = ["RUF001", "RUF002", "RUF003"]' in pyproject,
        "per-file-ignores allow docstring typography only",
        errors,
    )
    # Assert the invariant (scripts/validations is on mypy_path) rather than an exact
    # literal, so a legitimate additional base (e.g. "src" for the package layout) does not
    # trip this guard while an accidental removal still does. The value may be a quoted string
    # or a list, and the list may span multiple lines (a valid TOML reformat) — capture either
    # form with re.DOTALL. The *quoted* "scripts/validations" token (not a bare substring)
    # avoids a false-pass on a different path such as "scripts/validations-other".
    mypy_path = re.search(r'mypy_path\s*=\s*(?P<value>\[.*?\]|"[^"]*")', pyproject, re.DOTALL)
    _check(
        mypy_path is not None and '"scripts/validations"' in mypy_path.group("value"),
        "mypy resolves the validation gates' bootstrap imports",
        errors,
    )

    return report(logger, "F-031", errors)


if __name__ == "__main__":
    sys.exit(main())
