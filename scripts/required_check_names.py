#!/usr/bin/env python3
"""Derive required-check context names from the stub/real pairing (ADR 0037/0040).

The candidate required-status-check set is the rendered ``name:`` of every stub
job in ``.github/workflows/required-check-stubs.yml``. Those names are the
contract ``tests/test_required_check_stubs.py`` already enforces against the
real workflows — this module is that derivation without restating the names.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

#: Repo-relative stub workflow. Relocating the file is one assignment, not a
#: restated path at every call site.
DEFAULT_STUB_WORKFLOW = ".github/workflows/required-check-stubs.yml"

_GATE_CONDITION = re.compile(r"needs\.gate\.outputs\.(?P<key>\w+)\s*==\s*'false'")
_PYTHON_VERSION_EXPR = re.compile(r"\$\{\{\s*matrix\.python-version\s*\}\}")
_WORKFLOWS_ENTRY = re.compile(r"--workflow\s+(?P<key>\w+)=(?P<path>\.github/workflows/[\w.-]+\.yml)")


class CheckNameError(ValueError):
    """A workflow could not be rendered into check-context names."""


def load_workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CheckNameError(f"{path} is not a YAML mapping")
    return data


def rendered_job_names(workflow: dict[str, Any]) -> set[str]:
    """Every check context *workflow* can post.

    Only the ``python-version`` matrix axis is expanded — the single axis in use
    across this repository. Anything else is a loud error rather than a silent
    half-render.
    """
    names: set[str] = set()
    for job_id, job in workflow.get("jobs", {}).items():
        if not isinstance(job, dict):
            raise CheckNameError(f"job {job_id!r} is not a mapping")
        name = str(job.get("name", job_id))
        matrix = job.get("strategy", {}).get("matrix", {}) if isinstance(job.get("strategy"), dict) else {}
        if not isinstance(matrix, dict):
            matrix = {}
        axes = {k: v for k, v in matrix.items() if k != "fail-fast"}
        if not axes:
            if "${{" in name:
                raise CheckNameError(f"job {job_id!r} interpolates {name!r} with no matrix to expand")
            names.add(name)
            continue
        if set(axes) != {"python-version"}:
            raise CheckNameError(f"job {job_id!r} has an unsupported matrix axis: {sorted(axes)}")
        versions = axes["python-version"]
        if not isinstance(versions, list):
            raise CheckNameError(f"job {job_id!r} python-version matrix is not a list")
        for version in versions:
            rendered = _PYTHON_VERSION_EXPR.sub(str(version), name)
            if "${{" in rendered:
                raise CheckNameError(f"job {job_id!r} has an expression this cannot render: {name!r}")
            names.add(rendered)
    return names


def gate_workflow_map(stub_text: str, workflow_dir: Path) -> dict[str, Path]:
    """The gate job's ``key -> workflow file`` mapping, read from its own source."""
    mapping = {
        m.group("key"): workflow_dir.parent.parent / m.group("path") for m in _WORKFLOWS_ENTRY.finditer(stub_text)
    }
    if not mapping:
        raise CheckNameError("could not parse the gate job's --workflow arguments")
    return mapping


def stub_names_by_key(stubs: dict[str, Any]) -> dict[str, set[str]]:
    """Rendered stub names, grouped by the gate output each is conditioned on."""
    grouped: dict[str, set[str]] = {}
    for job_id, job in stubs.get("jobs", {}).items():
        if not isinstance(job, dict):
            continue
        condition = str(job.get("if", ""))
        match = _GATE_CONDITION.search(condition)
        if not match:
            continue
        single = {"jobs": {job_id: job}}
        grouped.setdefault(match.group("key"), set()).update(rendered_job_names(single))
    return grouped


def candidate_required_contexts(
    *,
    repo: Path | None = None,
    stub_workflow: str = DEFAULT_STUB_WORKFLOW,
) -> tuple[str, ...]:
    """Sorted unique check-context names ADR 0037 would require, derived not listed."""
    root = repo if repo is not None else Path(__file__).resolve().parent.parent
    stub_path = root / stub_workflow
    stubs = load_workflow(stub_path)
    names: set[str] = set()
    for group in stub_names_by_key(stubs).values():
        names.update(group)
    return tuple(sorted(names))
