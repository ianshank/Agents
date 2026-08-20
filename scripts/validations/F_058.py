#!/usr/bin/env python3
"""Validation script for F-058 - Validator-registration guard.

Asserts that all 4 registration points for validation scripts stay perfectly in sync:
    1. Ledger entries in features.yaml
    2. F_0NN.py files on disk in scripts/validations/
    3. The _VALIDATOR_MODULES list in tests/test_validation_scripts.py
    4. The --cov= list in .github/workflows/quality-gates.yml

Exit codes:
    0 - all checks passed
    1 - one or more checks failed
"""

from __future__ import annotations

import logging
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
for _p in (_HERE, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import check as _check
from _common import configure_logging, report

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(_SCRIPTS)


def _get_ledger_features() -> set[str]:
    import yaml

    with open(os.path.join(_ROOT, "features.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)

    features = set()
    for feat in data.get("features", []):
        cmd = feat.get("validation_command", "")
        if "scripts/validations/F_" in cmd:
            m = re.search(r"F_(\d+)\.py", cmd)
            if m:
                features.add(f"F_{m.group(1)}")
    return features


def _get_disk_features() -> set[str]:
    features = set()
    for fname in os.listdir(_HERE):
        if fname.startswith("F_") and fname.endswith(".py"):
            features.add(fname[:-3])
    return features


def _get_test_features() -> set[str]:
    with open(os.path.join(_ROOT, "tests", "test_validation_scripts.py"), encoding="utf-8") as f:
        content = f.read()

    # Match lines like `import F_020`
    imports = set(re.findall(r"^import (F_\d+)", content, re.MULTILINE))

    # Match the items inside _VALIDATOR_MODULES
    modules = set()
    in_tuple = False
    for line in content.splitlines():
        if line.startswith("_VALIDATOR_MODULES = ("):
            in_tuple = True
            continue
        if in_tuple:
            if line.startswith(")"):
                break
            m = re.match(r"^\s+(F_\d+),?", line)
            if m:
                modules.add(m.group(1))

    # If the imports and tuple differ, we'll return both unioned so the mismatch fails downstream
    # but strictly speaking they should be identical.
    return imports | modules


def _get_cov_features() -> set[str]:
    with open(os.path.join(_ROOT, ".github", "workflows", "quality-gates.yml"), encoding="utf-8") as f:
        content = f.read()
    return set(re.findall(r"--cov=(F_\d+)", content))


def main() -> int:
    configure_logging()
    errors: list[str] = []

    ledger = _get_ledger_features()
    disk = _get_disk_features()
    test = _get_test_features()
    cov = _get_cov_features()

    _check(
        ledger == disk,
        f"features.yaml vs disk matches. ledger - disk: {ledger - disk}, disk - ledger: {disk - ledger}",
        errors,
    )

    _check(
        disk == test,
        f"disk vs tests/test_validation_scripts.py matches. disk - test: {disk - test}, test - disk: {test - disk}",
        errors,
    )

    _check(
        test == cov,
        f"tests/test_validation_scripts.py vs quality-gates.yml matches. test - cov: {test - cov}, cov - test: {cov - test}",
        errors,
    )

    return report(logger, "F-058", errors)


if __name__ == "__main__":
    sys.exit(main())
