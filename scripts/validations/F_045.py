#!/usr/bin/env python3
"""Validation script for Feature F-045: dataset-lint skill and validate_skill assertions."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SCRIPTS)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)


def main() -> int:
    configure_logging()
    errors: list[str] = []

    # 1. Check skills/dataset-lint/SKILL.md exists
    skill_md = os.path.join(_ROOT, "skills", "dataset-lint", "SKILL.md")
    _check(os.path.isfile(skill_md), f"SKILL.md exists at {skill_md}", errors)

    # 2. Check skills/dataset-lint/scripts/lint_dataset.py exists and is importable
    lint_script = os.path.join(_ROOT, "skills", "dataset-lint", "scripts", "lint_dataset.py")
    _check(os.path.isfile(lint_script), f"lint_dataset.py exists at {lint_script}", errors)
    if os.path.isfile(lint_script):
        try:
            spec = importlib.util.spec_from_file_location("lint_dataset", lint_script)
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _check(True, "lint_dataset.py successfully imported", errors)
                # Verify modular parser registry
                _check(
                    hasattr(module, "FORMAT_PARSERS"),
                    "lint_dataset.py defines FORMAT_PARSERS registry mapping",
                    errors,
                )
            else:
                _check(False, "Could not create import spec for lint_dataset.py", errors)
        except Exception as e:
            _check(False, f"lint_dataset.py has syntax or import errors: {e}", errors)

        # Verify command line arguments in content
        with open(lint_script, encoding="utf-8") as f:
            lint_content = f.read()
        _check("--id-key" in lint_content, "lint_dataset.py supports --id-key option", errors)
        _check("--required-fields" in lint_content, "lint_dataset.py supports --required-fields option", errors)
        _check("--optional-fields" in lint_content, "lint_dataset.py supports --optional-fields option", errors)

    # 3. Check validate_skill.py has exit_nonzero, idempotent assertions and ASSERTION_GRADERS
    val_script = os.path.join(_ROOT, "scripts", "validate_skill.py")
    if os.path.isfile(val_script):
        with open(val_script, encoding="utf-8") as f:
            val_content = f.read()
        _check("exit_nonzero" in val_content, "validate_skill.py defines exit_nonzero assertion", errors)
        _check("idempotent" in val_content, "validate_skill.py defines idempotent assertion", errors)
        _check(
            "ASSERTION_GRADERS" in val_content, "validate_skill.py defines ASSERTION_GRADERS registry mapping", errors
        )
    else:
        _check(False, f"validate_skill.py missing at {val_script}", errors)

    # 4. Check marketplace.yaml includes dataset-lint
    mkt_yaml = os.path.join(_ROOT, "skills", "marketplace.yaml")
    if os.path.isfile(mkt_yaml):
        with open(mkt_yaml, encoding="utf-8") as f:
            mkt_data = yaml.safe_load(f)
        skills = [s["name"] for s in mkt_data.get("skills", [])]
        _check("dataset-lint" in skills, "dataset-lint is registered in marketplace.yaml", errors)
    else:
        _check(False, f"marketplace.yaml missing at {mkt_yaml}", errors)

    # 5. Check check_skill_script_drift.py tracks dataset-lint
    drift_script = os.path.join(_ROOT, "scripts", "check_skill_script_drift.py")
    if os.path.isfile(drift_script):
        with open(drift_script, encoding="utf-8") as f:
            drift_content = f.read()
        _check(
            "skills/dataset-lint/scripts/validate_skill.py" in drift_content,
            "check_skill_script_drift.py tracks dataset-lint's validate_skill.py",
            errors,
        )
    else:
        _check(False, f"check_skill_script_drift.py missing at {drift_script}", errors)

    return report(logger, "F-045", errors)


if __name__ == "__main__":
    raise SystemExit(main())
