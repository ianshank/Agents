#!/usr/bin/env python3
"""Validation script for F-029 — model-bench marketplace skill.

Deterministic and offline. Asserts the model-bench skill has the v2.0 layout,
that its runner forwards to the harness compare/campaign over the bundled
echo-target fixtures (no network), that it passes structural+behavioral
validation, and that it is registered in the marketplace with a matching version.

Exit codes: 0 all checks passed; 1 one or more failed.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import yaml
from _common import check as _check
from _common import configure_logging, report
from validate_skill import check_structural, parse_frontmatter  # canonical validator, read-only

_SKILL = os.path.join(_ROOT, "skills", "model-bench")
_SKILL_SCRIPTS = os.path.join(_SKILL, "scripts")


def validate_f029() -> int:
    configure_logging()
    logger = logging.getLogger("validations.F-029")
    errors: list[str] = []

    # --- v2.0 layout ---
    fm, _ = parse_frontmatter(os.path.join(_SKILL, "SKILL.md"))
    fm = fm or {}
    _check(str(fm.get("validator_version")) == "2.0", "frontmatter validator_version is 2.0", errors)
    _check(os.path.isdir(os.path.join(_SKILL, "tests")), "tests/ directory exists", errors)
    _check(os.path.isfile(os.path.join(_SKILL, "ruff.toml")), "ruff.toml exists", errors)

    struct_errs, _ = check_structural(_SKILL, os.path.join(_SKILL, "evals", "evals.json"))
    _check(not struct_errs, f"skill passes structural validation ({struct_errs})", errors)

    # --- runner forwards to the harness over the echo fixtures (offline) ---
    if _SKILL_SCRIPTS not in sys.path:
        sys.path.insert(0, _SKILL_SCRIPTS)
    import run as model_bench_run

    _check(model_bench_run.main([]) == 2, "no-args prints usage and exits 2", errors)

    compare_cfg = os.path.join(_SKILL, "evals", "fixtures", "compare.yaml")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = model_bench_run.main(["compare", "--config", compare_cfg, "--offline"])
    _check(rc == 0 and "good-model > bad-model" in buf.getvalue(), "compare ranks the better model first", errors)

    # --- marketplace registration with a matching version ---
    with open(os.path.join(_ROOT, "skills", "marketplace.yaml"), encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    entry = next((s for s in registry["skills"] if s["name"] == "model-bench"), None)
    _check(entry is not None, "model-bench listed in marketplace.yaml", errors)
    if entry is not None:
        _check(str(entry["version"]) == str(fm.get("version")), "marketplace version matches SKILL.md", errors)

    return report(logger, "F-029", errors)


if __name__ == "__main__":
    sys.exit(validate_f029())
